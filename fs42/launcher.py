import argparse
import logging
import select
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path

from fs42.channel_validator import validate_channels
from fs42.channel_control import write_channel_command as write_player_channel_command
from fs42.compiled_sync import CompiledSyncError, compiled_status, download_compiled, print_status, upload_compiled
from fs42.config import PROJECT_ROOT, apply_cli_overrides, ensure_config_file, load_config, save_config
from fs42.doctor import run_doctor
from fs42.logging_setup import setup_logging
from fs42.media_links import discover_channels, sync_links_from_configs
from fs42.mega import MegaError, guess_mega_remote, maybe_set_xdg_runtime_dir, mount_mega


RUNTIME_ASSETS = {
    "static.mp4": "static.mp4",
    "standby.png": "standby.png",
    "brb.png": "brb.png",
    "off_air_pattern.mp4": "off_air_pattern.mp4",
    "signoff.mp4": "signoff.mp4",
}


def display_args(args) -> list[str]:
    flags = []
    if args.windowed:
        flags.append("--windowed")
    if args.fullscreen:
        flags.append("--fullscreen")
    if args.window_width:
        flags.extend(["--window-width", str(args.window_width)])
    if args.window_height:
        flags.extend(["--window-height", str(args.window_height)])
    if args.window_x is not None:
        flags.extend(["--window-x", str(args.window_x)])
    if args.window_y is not None:
        flags.extend(["--window-y", str(args.window_y)])
    if args.combined_window is True:
        flags.append("--combined-window")
    elif args.combined_window is False:
        flags.append("--separate-osd-window")
    return flags


def player_args(args) -> list[str]:
    flags = display_args(args)
    if args.direct_start_seek:
        flags.append("--direct-start-seek")
    return flags


def ensure_runtime_files(config: dict):
    runtime_dir = PROJECT_ROOT / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "catalogs").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "schedules").mkdir(parents=True, exist_ok=True)
    Path(config["logs_dir"]).mkdir(parents=True, exist_ok=True)

    docs_dir = PROJECT_ROOT / "docs"
    for source_name, destination_name in RUNTIME_ASSETS.items():
        source = docs_dir / source_name
        destination = runtime_dir / destination_name
        if source.exists() and not destination.exists():
            shutil.copy2(source, destination)

    Path(config["channel_socket"]).parent.mkdir(parents=True, exist_ok=True)
    Path(config["channel_socket"]).touch(exist_ok=True)
    Path(config["status_socket"]).parent.mkdir(parents=True, exist_ok=True)
    Path(config["status_socket"]).touch(exist_ok=True)


def prompt(default: str, message: str) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{message}{suffix}: ").strip()
    return value or default


def first_run_setup(interactive: bool = True) -> dict:
    config_file = ensure_config_file()
    config = load_config(config_file)
    changed = False
    run_wizard = not config.get("first_run_complete", False)

    if not config.get("mega_remote"):
        guessed = guess_mega_remote()
        if guessed:
            config["mega_remote"] = guessed
            changed = True
        elif run_wizard and interactive and sys.stdin.isatty():
            remote = prompt("", "MEGA rclone remote name (leave blank to skip)")
            if remote:
                config["mega_remote"] = remote.rstrip(":")
                changed = True

    if run_wizard and interactive and sys.stdin.isatty():
        if config.get("mega_remote"):
            mount_point = prompt(config.get("mega_mount_point", "~/mega"), "MEGA mount point")
            if mount_point != config.get("mega_mount_point"):
                config["mega_mount_point"] = mount_point
                changed = True
        if not config.get("media_root"):
            media_root = prompt("", "Media root path (leave blank to use repo-relative channel paths)")
            if media_root:
                config["media_root"] = media_root
                changed = True

    if run_wizard and interactive and sys.stdin.isatty():
        config["first_run_complete"] = True
        changed = True

    if changed:
        save_config(config, config_file)
        config = load_config(config_file)

    ensure_runtime_files(config)
    return config


def write_channel_command(command: str, config: dict):
    write_player_channel_command(command, channel_socket=config["channel_socket"])


def start_process(command: list[str], log_file: Path) -> subprocess.Popen:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handle = log_file.open("a", encoding="utf-8")
    return subprocess.Popen(command, cwd=PROJECT_ROOT, stdout=handle, stderr=subprocess.STDOUT)


def cleanup(processes: list[subprocess.Popen]):
    for process in processes:
        if process.poll() is None:
            try:
                process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass

    deadline = time.time() + 5
    for process in processes:
        while process.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        if process.poll() is None:
            process.terminate()


def keyboard_loop(processes: list[subprocess.Popen], config: dict):
    print()
    print("FS42 Running")
    print("UP/DOWN arrows = channel change")
    print("Ctrl+C = stop everything")
    print()

    if not sys.stdin.isatty():
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        return

    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        while all(process.poll() is None for process in processes):
            readable, _, _ = select.select([sys.stdin], [], [], 0.2)
            if not readable:
                continue
            key = sys.stdin.read(1)
            if key == "\x1b":
                sequence = sys.stdin.read(2)
                if sequence == "[A":
                    print("Channel up")
                    write_channel_command("up", config)
                elif sequence == "[B":
                    print("Channel down")
                    write_channel_command("down", config)
            elif key == "\x03":
                raise KeyboardInterrupt
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def validate_or_exit(strict: bool = False) -> int:
    report = validate_channels()
    print(report.render())
    if report.errors or (strict and report.warnings):
        return 1
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Portable FieldStation42 launcher.")
    parser.add_argument("--windowed", action="store_true", help="Run player and OSD in desktop windows.")
    parser.add_argument("--fullscreen", action="store_true", help="Run player and OSD fullscreen.")
    parser.add_argument("--window-width", type=int, help="Window width for --windowed.")
    parser.add_argument("--window-height", type=int, help="Window height for --windowed.")
    parser.add_argument("--window-x", type=int, help="Window x position for windowed playback.")
    parser.add_argument("--window-y", type=int, help="Window y position for windowed playback.")
    window_group = parser.add_mutually_exclusive_group()
    window_group.add_argument(
        "--combined-window",
        dest="combined_window",
        action="store_true",
        default=None,
        help="Stack the OSD over the MPV window in windowed mode.",
    )
    window_group.add_argument(
        "--separate-osd-window",
        dest="combined_window",
        action="store_false",
        help="Use a separate decorated OSD window in windowed mode.",
    )
    parser.add_argument(
        "--direct-start-seek",
        action="store_true",
        help="Ask MPV to start scheduled files at their target timestamp immediately.",
    )
    parser.add_argument("--doctor", action="store_true", help="Run health checks and exit.")
    parser.add_argument("--validate", action="store_true", help="Validate channels and exit.")
    parser.add_argument("--strict", action="store_true", help="Treat validation warnings as failures.")
    parser.add_argument("--no-validate", action="store_true", help="Skip channel validation before playback.")
    parser.add_argument("--no-mount", action="store_true", help="Do not attempt to mount MEGA.")
    parser.add_argument("--no-osd", action="store_true", help="Start the player without the OSD overlay.")
    parser.add_argument("--discover-media-channels", action="store_true", help="Write station configs from MEGA FS42_MEDIA/Channels.")
    parser.add_argument("--sync-media-links", action="store_true", help="Refresh local symlinks from channel configs and exit.")
    parser.add_argument("--upload-compiled", action="store_true", help="Upload compiled catalogs, schedules, and cache DB to MEGA.")
    parser.add_argument("--sync-compiled", action="store_true", help="Download newer compiled catalogs, schedules, and cache DB from MEGA.")
    parser.add_argument("--force-sync-compiled", action="store_true", help="Replace local compiled files with the MEGA copy.")
    parser.add_argument("--compiled-status", action="store_true", help="Show local/remote compiled cache status.")
    parser.add_argument("--no-sync-compiled", action="store_true", help="Do not auto-download compiled files before validation/start.")
    parser.add_argument(
        "-t",
        "--transition",
        choices=["long", "short", "none"],
        help="Transition effect to use on channel change.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose launcher/player logging.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config = first_run_setup(interactive=not (args.doctor or args.validate))
    config.update(apply_cli_overrides({}, args))
    setup_logging("launcher", "sync.log", verbose=args.verbose)
    logger = logging.getLogger("launcher")

    if args.doctor:
        report = run_doctor(strict_channels=args.strict)
        print(report.render())
        return 0 if report.ok() else 1

    maybe_set_xdg_runtime_dir()
    if not args.no_mount and config.get("mega_remote"):
        try:
            mount_mega(config)
        except MegaError as exc:
            print("MEGA mount failed.")
            print(str(exc))
            logger.exception("MEGA mount failed")
            return 1

    if args.discover_media_channels:
        configs = discover_channels(config=config, write=True)
        link_count = sync_links_from_configs(config)
        print(f"Wrote {len(configs)} channel config(s).")
        print(f"Synced {link_count} media link(s).")
        return 0

    if args.sync_media_links:
        link_count = sync_links_from_configs(config)
        print(f"Synced {link_count} media link(s).")
        return 0

    if config.get("auto_sync_media_links", True):
        sync_links_from_configs(config)

    if args.upload_compiled:
        try:
            manifest = upload_compiled(config)
            print(f"Uploaded {len(manifest['files'])} compiled file(s).")
        except CompiledSyncError as exc:
            print(f"Compiled upload failed: {exc}")
            return 1
        return 0

    if args.sync_compiled or args.force_sync_compiled:
        try:
            changed, reason = download_compiled(config, force=args.force_sync_compiled)
            print(("Downloaded compiled files. " if changed else "Skipped download. ") + reason)
        except CompiledSyncError as exc:
            print(f"Compiled sync failed: {exc}")
            return 1
        return 0

    if args.compiled_status:
        try:
            print_status(compiled_status(config))
        except CompiledSyncError as exc:
            print(f"Compiled status failed: {exc}")
            return 1
        return 0

    if config.get("auto_sync_compiled", True) and not args.no_sync_compiled:
        try:
            changed, reason = download_compiled(config)
            if changed:
                logger.info("Downloaded compiled files: %s", reason)
            else:
                logger.info("Compiled sync skipped: %s", reason)
        except CompiledSyncError as exc:
            logger.warning("Compiled auto-sync skipped: %s", exc)

    if args.validate:
        return validate_or_exit(strict=args.strict)

    if not args.no_validate:
        validation_exit = validate_or_exit(strict=args.strict)
        if validation_exit:
            print()
            print("FS42 did not start because channel validation found errors.")
            print("Run with --no-validate only when you intentionally want to debug playback anyway.")
            return validation_exit

    python = sys.executable
    player_command = [python, str(PROJECT_ROOT / "field_player.py"), *player_args(args)]
    if args.transition:
        player_command.extend(["--transition", args.transition])
    if args.verbose:
        player_command.append("--verbose")

    processes = [
        start_process(player_command, Path(config["logs_dir"]) / "player.stdout.log"),
    ]

    if not args.no_osd:
        osd_command = [python, str(PROJECT_ROOT / "fs42" / "osd" / "main.py"), *display_args(args)]
        processes.append(start_process(osd_command, Path(config["logs_dir"]) / "osd.log"))

    try:
        keyboard_loop(processes, config)
    except KeyboardInterrupt:
        print()
        print("Stopping FS42...")
    finally:
        cleanup(processes)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
