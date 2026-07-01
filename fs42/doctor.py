import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from fs42.channel_validator import validate_channels
from fs42.compiled_sync import compiled_db_counts
from fs42.config import PROJECT_ROOT, config_path, load_config
from fs42.mega import is_mount_point, list_remotes, rclone_available


@dataclass
class DoctorCheck:
    name: str
    status: str
    detail: str = ""

    def render(self) -> str:
        detail = f" - {self.detail}" if self.detail else ""
        return f"{self.status:<5} {self.name}{detail}"


class DoctorReport:
    def __init__(self):
        self.checks: list[DoctorCheck] = []

    def pass_(self, name: str, detail: str = ""):
        self.checks.append(DoctorCheck(name, "PASS", detail))

    def warn(self, name: str, detail: str = ""):
        self.checks.append(DoctorCheck(name, "WARN", detail))

    def fail(self, name: str, detail: str = ""):
        self.checks.append(DoctorCheck(name, "FAIL", detail))

    def ok(self) -> bool:
        return not any(check.status == "FAIL" for check in self.checks)

    def render(self) -> str:
        lines = ["FieldStation42 Doctor", ""]
        lines.extend(check.render() for check in self.checks)
        failures = len([check for check in self.checks if check.status == "FAIL"])
        warnings = len([check for check in self.checks if check.status == "WARN"])
        lines.extend(["", f"Summary: {failures} failure(s), {warnings} warning(s)"])
        return "\n".join(lines)


def writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        test_file = path / ".fs42_write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        return True
    except OSError:
        return False


def run_doctor(strict_channels: bool = False) -> DoctorReport:
    report = DoctorReport()

    try:
        config = load_config()
        report.pass_("config", str(config_path()))
    except Exception as exc:
        report.fail("config", str(exc))
        return report

    runtime_dir = PROJECT_ROOT / "runtime"
    logs_dir = Path(config["logs_dir"])
    report.pass_("runtime dir", str(runtime_dir)) if runtime_dir.exists() else report.fail("runtime dir", str(runtime_dir))
    report.pass_("logs dir", str(logs_dir)) if writable(logs_dir) else report.fail("logs dir", f"Not writable: {logs_dir}")

    db_path = Path(config["db_path"])
    if db_path.exists():
        report.pass_("cache db", str(db_path))
    else:
        report.warn("cache db", f"Missing: {db_path}")

    schedule_dir = Path(config.get("compiled_schedule_dir") or runtime_dir / "schedules")
    schedules = list(schedule_dir.glob("*.pkl")) if schedule_dir.exists() else []
    db_counts = compiled_db_counts(config)
    if schedules or db_counts["schedule_blocks"] > 0:
        detail = f"{db_counts['schedule_blocks']} DB block(s)"
        if schedules:
            detail += f"; {len(schedules)} legacy file(s) in {schedule_dir}"
        report.pass_("compiled schedules", detail)
    else:
        report.fail("compiled schedules", f"No DB schedule blocks or .pkl schedules in {schedule_dir}")

    media_root = config.get("media_root")
    if media_root:
        media_root_path = Path(media_root)
        if media_root_path.exists():
            report.pass_("media root", str(media_root_path))
        else:
            report.fail("media root", f"Missing: {media_root_path}")
    else:
        report.warn("media root", "No media_root configured; channel paths resolve relative to the repo.")

    if config.get("mega_remote"):
        if not rclone_available():
            report.fail("MEGA/rclone", "rclone is not installed or is not on PATH.")
        else:
            remotes = list_remotes()
            remote = config["mega_remote"].rstrip(":")
            if remote in remotes:
                report.pass_("MEGA remote", remote)
            else:
                report.fail("MEGA remote", f"{remote} not found in rclone remotes.")

            mount_point = Path(config.get("mega_mount_point") or "~/mega").expanduser()
            if is_mount_point(mount_point):
                report.pass_("MEGA mount", str(mount_point))
            else:
                report.warn("MEGA mount", f"Not mounted: {mount_point}")
    else:
        report.warn("MEGA/rclone", "No mega_remote configured.")

    for directory in (PROJECT_ROOT / "confs", runtime_dir, logs_dir):
        if os.access(directory, os.R_OK | os.W_OK):
            report.pass_("permissions", f"read/write: {directory}")
        else:
            report.fail("permissions", f"Need read/write: {directory}")

    channel_report = validate_channels()
    if channel_report.errors:
        report.fail("channels", f"{len(channel_report.errors)} error(s); run launch.sh --validate for details.")
    elif strict_channels and channel_report.warnings:
        report.fail("channels", f"{len(channel_report.warnings)} warning(s) treated as failures.")
    elif channel_report.warnings:
        report.warn("channels", f"{len(channel_report.warnings)} warning(s).")
    else:
        report.pass_("channels", "All configured channels validated.")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run FieldStation42 health checks.")
    parser.add_argument("--strict-channels", action="store_true", help="Treat channel warnings as doctor failures.")
    args = parser.parse_args()

    report = run_doctor(strict_channels=args.strict_channels)
    print(report.render())
    return 0 if report.ok() else 1


if __name__ == "__main__":
    raise SystemExit(main())
