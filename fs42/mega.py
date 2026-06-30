import logging
import os
import shutil
import subprocess
from pathlib import Path

from fs42.config import load_config


class MegaError(RuntimeError):
    pass


def rclone_path() -> str | None:
    return shutil.which("rclone")


def rclone_available() -> bool:
    return rclone_path() is not None


def list_remotes() -> list[str]:
    if not rclone_available():
        return []
    result = subprocess.run(
        ["rclone", "listremotes"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line.rstrip(":") for line in result.stdout.splitlines() if line.strip()]


def is_mount_point(path: str | Path) -> bool:
    mount_point = str(path)
    if not shutil.which("findmnt"):
        return Path(mount_point).is_mount()
    result = subprocess.run(
        ["findmnt", "-M", mount_point],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def mount_mega(config: dict | None = None) -> bool:
    config = config or load_config()
    logger = logging.getLogger("mega")

    remote = config.get("mega_remote")
    if not remote:
        logger.info("No MEGA remote configured; skipping mount.")
        return False

    if not rclone_available():
        raise MegaError("rclone is not installed or is not on PATH.")

    mount_point = Path(config.get("mega_mount_point") or "~/mega").expanduser()
    mount_point.mkdir(parents=True, exist_ok=True)

    if is_mount_point(mount_point):
        logger.info("MEGA mount already active at %s", mount_point)
        return True

    remote_spec = remote if remote.endswith(":") else f"{remote}:"
    options = config.get("mega_mount_options") or []
    command = ["rclone", "mount", remote_spec, str(mount_point), *options, "--daemon"]
    logger.info("Mounting %s at %s", remote_spec, mount_point)

    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "rclone mount failed without output."
        raise MegaError(message)

    if not is_mount_point(mount_point):
        raise MegaError(f"rclone reported success, but {mount_point} is not mounted.")

    return True


def unmount_mega(config: dict | None = None) -> bool:
    config = config or load_config()
    mount_point = Path(config.get("mega_mount_point") or "~/mega").expanduser()
    if not is_mount_point(mount_point):
        return False

    command = ["fusermount", "-u", str(mount_point)]
    if shutil.which("fusermount3"):
        command[0] = "fusermount3"
    elif not shutil.which("fusermount"):
        command = ["umount", str(mount_point)]

    result = subprocess.run(command, check=False, capture_output=True, text=True)
    return result.returncode == 0


def guess_mega_remote() -> str:
    for remote in list_remotes():
        if remote.lower() == "mega":
            return remote
    remotes = list_remotes()
    if len(remotes) == 1:
        return remotes[0]
    return ""


def maybe_set_xdg_runtime_dir():
    if os.environ.get("XDG_RUNTIME_DIR"):
        return
    uid = os.getuid()
    candidate = Path(f"/run/user/{uid}")
    if candidate.exists():
        os.environ["XDG_RUNTIME_DIR"] = str(candidate)
