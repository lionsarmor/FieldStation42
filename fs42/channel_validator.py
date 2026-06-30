import argparse
import datetime
import json
import logging
import os
import pickle
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from fs42.config import PROJECT_ROOT, load_config, normalize_station_config, resolve_project_path
from fs42.logging_setup import setup_logging


MEDIA_EXTENSIONS = {".mp4", ".mpg", ".mpeg", ".avi", ".mov", ".mkv", ".ts", ".m4v", ".webm", ".wmv"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
NO_SCHEDULE_TYPES = {"guide", "streaming"}


@dataclass
class ValidationIssue:
    level: str
    channel: str
    message: str
    detail: str = ""

    def render(self) -> str:
        prefix = f"[{self.level}]"
        subject = f" {self.channel}" if self.channel else ""
        detail = f"\n      {self.detail}" if self.detail else ""
        return f"{prefix}{subject}: {self.message}{detail}"


class ValidationReport:
    def __init__(self):
        self.issues: list[ValidationIssue] = []
        self._seen: set[tuple[str, str, str, str]] = set()

    def error(self, channel: str, message: str, detail: str = ""):
        self._add(ValidationIssue("ERROR", channel, message, detail))

    def warning(self, channel: str, message: str, detail: str = ""):
        self._add(ValidationIssue("WARN", channel, message, detail))

    def _add(self, issue: ValidationIssue):
        key = (issue.level, issue.channel, issue.message, issue.detail)
        if key in self._seen:
            return
        self._seen.add(key)
        self.issues.append(issue)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.level == "ERROR"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.level == "WARN"]

    def ok(self) -> bool:
        return not self.errors

    def render(self, max_issues: int = 200) -> str:
        lines = ["FieldStation42 Channel Validation", ""]
        if not self.issues:
            lines.append("PASS: all configured channels validated.")
            return "\n".join(lines)

        for issue in self.issues[:max_issues]:
            lines.append(issue.render())
        if len(self.issues) > max_issues:
            lines.append(f"... {len(self.issues) - max_issues} more issue(s) omitted. See logs/channels.log or rerun with a narrower channel set after repairs.")

        lines.extend(
            [
                "",
                f"Summary: {len(self.errors)} error(s), {len(self.warnings)} warning(s)",
            ]
        )
        return "\n".join(lines)


def station_config_files() -> list[Path]:
    config_dir = PROJECT_ROOT / "confs"
    main_config = resolve_project_path("confs/main_config.json")
    return sorted(
        path
        for path in config_dir.glob("*.json")
        if path != main_config and not path.name.startswith(".")
    )


def is_url(path_value: str) -> bool:
    parsed = urlparse(path_value)
    return parsed.scheme in {"http", "https", "rtmp", "rtsp", "mms"}


def media_files(path: Path) -> list[Path]:
    if not path.exists() or not path.is_dir():
        return []
    found = []
    for root, _, files in os.walk(path, followlinks=True):
        for filename in files:
            item = Path(root) / filename
            if item.suffix.lower() in MEDIA_EXTENSIONS:
                found.append(item)
    return found


def image_files(path: Path) -> list[Path]:
    if not path.exists() or not path.is_dir():
        return []
    found = []
    for root, _, files in os.walk(path, followlinks=True):
        for filename in files:
            item = Path(root) / filename
            if item.suffix.lower() in IMAGE_EXTENSIONS:
                found.append(item)
    return found


def resolve_media_reference(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def collect_object_paths(obj, seen: set[int] | None = None, depth: int = 0) -> set[str]:
    if seen is None:
        seen = set()
    if depth > 8:
        return set()

    obj_id = id(obj)
    if obj_id in seen:
        return set()
    seen.add(obj_id)

    paths = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "path" and isinstance(value, str):
                paths.add(value)
            else:
                paths.update(collect_object_paths(value, seen, depth + 1))
    elif isinstance(obj, (list, tuple, set)):
        for value in obj:
            paths.update(collect_object_paths(value, seen, depth + 1))
    elif hasattr(obj, "__dict__"):
        value = getattr(obj, "path", None)
        if isinstance(value, str):
            paths.add(value)
        paths.update(collect_object_paths(vars(obj), seen, depth + 1))

    return paths


def collect_tags(station: dict) -> set[str]:
    tags = set()
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
        for slot in station.get(day, {}).values():
            slot_tags = slot.get("tags")
            if isinstance(slot_tags, list):
                tags.update(slot_tags)
            elif isinstance(slot_tags, str):
                tags.add(slot_tags)
    return tags


def load_station_file(path: Path, report: ValidationReport) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as config_file:
            data = json.load(config_file)
    except json.JSONDecodeError as exc:
        report.error(path.name, "Invalid JSON.", str(exc))
        return None
    except OSError as exc:
        report.error(path.name, "Could not read station config.", str(exc))
        return None

    if "station_conf" not in data or not isinstance(data["station_conf"], dict):
        report.error(path.name, "Missing top-level station_conf object.")
        return None
    return data["station_conf"]


def validate_station_paths(station: dict, report: ValidationReport):
    name = station.get("network_name", "<unnamed>")
    content_dir = Path(station["content_dir"]) if station.get("content_dir") else None
    network_type = station.get("network_type", "standard")

    if network_type not in NO_SCHEDULE_TYPES:
        if not content_dir:
            report.error(name, "Missing content_dir.")
        elif not content_dir.exists():
            report.error(name, "Content directory is missing.", str(content_dir))
        elif not media_files(content_dir):
            report.error(name, "Content directory contains no playable media.", str(content_dir))

    for key in ("sign_off_video", "off_air_video", "off_air_image", "standby_image", "be_right_back_media"):
        if station.get(key):
            expected = Path(station[key])
            if not expected.exists():
                report.error(name, f"{key} does not exist.", str(expected))

    if content_dir and content_dir.exists():
        for tag in collect_tags(station):
            tag_dir = content_dir / tag
            if not tag_dir.exists():
                report.error(name, f"Scheduled tag '{tag}' has no matching media directory.", str(tag_dir))
            elif not media_files(tag_dir):
                report.error(name, f"Scheduled tag '{tag}' has an empty media directory.", str(tag_dir))

        if not station.get("commercial_free", False) and station.get("commercial_dir"):
            commercial_dir = content_dir / station["commercial_dir"]
            if not commercial_dir.exists():
                report.error(name, "Commercial directory is missing.", str(commercial_dir))
            elif not media_files(commercial_dir):
                report.error(name, "Commercial directory contains no playable media.", str(commercial_dir))

        if station.get("bump_dir"):
            bump_dir = content_dir / station["bump_dir"]
            if not bump_dir.exists():
                report.error(name, "Bumper directory is missing.", str(bump_dir))
            elif not media_files(bump_dir):
                report.error(name, "Bumper directory contains no playable media.", str(bump_dir))

    if station.get("logo_dir"):
        logo_dir = Path(station["logo_dir"])
        if not logo_dir.is_absolute() and content_dir:
            logo_dir = content_dir / logo_dir
        if not logo_dir.exists():
            report.warning(name, "Artwork/logo directory is missing.", str(logo_dir))
        elif not image_files(logo_dir):
            report.warning(name, "Artwork/logo directory contains no images.", str(logo_dir))
        if station.get("default_logo"):
            logo = logo_dir / station["default_logo"]
            if not logo.exists():
                report.warning(name, "Default channel artwork is missing.", str(logo))
    else:
        report.warning(name, "No artwork/logo directory configured.")


def validate_schedule(station: dict, report: ValidationReport):
    name = station.get("network_name", "<unnamed>")
    network_type = station.get("network_type", "standard")
    if network_type in NO_SCHEDULE_TYPES:
        return

    schedule_value = station.get("schedule_path")
    if not schedule_value:
        report.error(name, "Missing schedule_path.")
        return
    schedule_path = Path(schedule_value)
    if not schedule_path.exists():
        report.error(name, "Schedule file is missing.", str(schedule_path))
        return

    try:
        with schedule_path.open("rb") as schedule_file:
            schedule = pickle.load(schedule_file)
    except Exception as exc:
        report.error(name, "Schedule file could not be loaded.", str(exc))
        return

    if not schedule:
        report.error(name, "Schedule exists but contains no programming blocks.", str(schedule_path))
        return

    previous_end = None
    missing_media = set()
    for index, block in enumerate(schedule):
        start = getattr(block, "start_time", None)
        end = getattr(block, "end_time", None)
        if not isinstance(start, datetime.datetime) or not isinstance(end, datetime.datetime):
            report.error(name, f"Schedule block {index} has invalid timestamps.", repr(block))
        elif start >= end:
            report.error(name, f"Schedule block {index} starts after or at its end.", f"{start} >= {end}")
        elif previous_end and start < previous_end:
            report.error(name, f"Schedule block {index} overlaps the previous block.", f"{start} < {previous_end}")
        previous_end = end

        plan = getattr(block, "plan", None)
        if not plan:
            report.error(name, f"Schedule block {index} has an empty playlist/plan.", repr(block))
            continue

        for plan_index, entry in enumerate(plan):
            duration = getattr(entry, "duration", None)
            if duration is None or duration <= 0:
                report.error(name, f"Schedule block {index}, playlist entry {plan_index} has invalid duration.", repr(entry))
            entry_path = getattr(entry, "path", None)
            is_stream = getattr(entry, "is_stream", False)
            if not entry_path:
                report.error(name, f"Schedule block {index}, playlist entry {plan_index} is missing a media path.")
            elif not is_stream and not is_url(entry_path):
                resolved = resolve_media_reference(entry_path)
                if not resolved.exists():
                    missing_media.add(str(resolved))

    for path_value in collect_object_paths(schedule):
        if is_url(path_value):
            continue
        resolved = resolve_media_reference(path_value)
        if not resolved.exists():
            missing_media.add(str(resolved))

    for missing_path in sorted(missing_media):
        report.error(name, "Scheduled media file is missing.", missing_path)


def validate_catalog(station: dict, report: ValidationReport):
    name = station.get("network_name", "<unnamed>")
    network_type = station.get("network_type", "standard")
    if network_type in {"guide", "streaming"}:
        return
    catalog_value = station.get("catalog_path")
    if not catalog_value:
        report.error(name, "Missing catalog_path.")
        return
    catalog_path = Path(catalog_value)
    if not catalog_path.exists():
        report.error(name, "Catalog/playlist file is missing.", str(catalog_path))
        return
    try:
        with catalog_path.open("rb") as catalog_file:
            catalog = pickle.load(catalog_file)
    except Exception as exc:
        report.error(name, "Catalog/playlist file could not be loaded.", str(exc))
        return
    if not catalog:
        report.error(name, "Catalog/playlist file is empty.", str(catalog_path))


def validate_channels() -> ValidationReport:
    setup_logging("channels", "channels.log")
    logger = logging.getLogger("channels")
    report = ValidationReport()
    server_config = load_config()
    station_files = station_config_files()

    if not station_files:
        report.error("confs", "No station JSON files were found.", str(PROJECT_ROOT / "confs"))
        return report

    seen_channels = {}
    seen_names = {}
    stations = []
    for path in station_files:
        station = load_station_file(path, report)
        if station is None:
            continue
        station = normalize_station_config(station, server_config)
        station["_config_file"] = str(path)
        stations.append(station)

        channel_number = station.get("channel_number")
        if channel_number in seen_channels:
            report.error(
                station.get("network_name", path.name),
                "Duplicate channel number.",
                f"{channel_number} also used by {seen_channels[channel_number]}",
            )
        else:
            seen_channels[channel_number] = station.get("network_name", path.name)

        name = station.get("network_name")
        if name in seen_names:
            report.error(name or path.name, "Duplicate network_name.", f"Also defined in {seen_names[name]}")
        else:
            seen_names[name] = path.name

    for station in stations:
        logger.info("Validating %s", station.get("network_name"))
        validate_station_paths(station, report)
        validate_catalog(station, report)
        validate_schedule(station, report)

    logger.info("\n%s", report.render(max_issues=1000000))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate FieldStation42 channel configs and schedules.")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    args = parser.parse_args()

    report = validate_channels()
    print(report.render())
    if report.errors or (args.strict and report.warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
