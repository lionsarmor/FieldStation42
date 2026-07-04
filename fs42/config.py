import copy
import json
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "confs" / "main_config.json"


DEFAULT_CONFIG = {
    "fullscreen": True,
    "window_width": 1280,
    "window_height": 720,
    "window_x": 80,
    "window_y": 60,
    "combined_window": True,
    "osd_scale": 1.0,
    "media_root": "",
    "mega_remote": "",
    "mega_mount_point": "~/mega",
    "first_run_complete": False,
    "auto_sync_media_links": True,
    "mega_mount_options": [
        "--vfs-cache-mode",
        "full",
        "--vfs-read-ahead",
        "2G",
        "--buffer-size",
        "512M",
        "--vfs-cache-max-size",
        "50G",
        "--vfs-cache-max-age",
        "24h",
        "--dir-cache-time",
        "72h",
        "--poll-interval",
        "0",
        "--transfers",
        "4",
        "--checkers",
        "8",
    ],
    "channel_socket": "runtime/channel.socket",
    "status_socket": "runtime/play_status.socket",
    "time_format": "%H:%M",
    "date_time_format": "%Y-%m-%dT%H:%M:%S",
    "db_path": "runtime/fs42_fluid.db",
    "start_mpv": True,
    "mpv_volume": 100,
    "mpv_volume_max": 100,
    "mpv_audio_client_name": "FieldStation42",
    "mpv_use_user_config": False,
    "mpv_subtitles_enabled": False,
    "logs_dir": "logs",
    "compiled_schedule_dir": "runtime/schedules",
    "compiled_remote_path": "FS42_MEDIA/Compiled",
    "auto_sync_compiled": True,
    "mpv_direct_start_seek": True,
    "mpv_hr_seek": False,
    "mpv_startup_wait_seconds": 1.0,
    "failed_channel_retry_seconds": 1,
    "day_parts": {
        "morning": {"start_hour": 6, "end_hour": 10},
        "daytime": {"start_hour": 10, "end_hour": 18},
        "prime": {"start_hour": 18, "end_hour": 23},
        "late": {"start_hour": 23, "end_hour": 2},
        "overnight": {"start_hour": 2, "end_hour": 6},
    },
}


PROJECT_PATH_KEYS = {
    "channel_socket",
    "status_socket",
    "db_path",
    "logs_dir",
    "compiled_schedule_dir",
}


STATION_PROJECT_PATH_KEYS = {
    "catalog_path",
    "schedule_path",
    "runtime_dir",
    "sign_off_video",
    "off_air_video",
    "off_air_image",
    "standby_image",
    "be_right_back_media",
    "sound_to_play",
}


def config_path() -> Path:
    configured = os.environ.get("FS42_CONFIG")
    if configured:
        return resolve_project_path(configured)
    return DEFAULT_CONFIG_PATH


def coerce_value(value: str):
    normalized = value.strip()
    lowered = normalized.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"none", "null"}:
        return None
    try:
        return int(normalized)
    except ValueError:
        pass
    try:
        return float(normalized)
    except ValueError:
        pass
    return normalized.strip("\"'")


def parse_key_value_config(text: str) -> dict:
    parsed = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = coerce_value(value)
    return parsed


def load_config(path: str | Path | None = None, create: bool = False) -> dict:
    path = Path(path) if path else config_path()
    if path.exists():
        with path.open("r", encoding="utf-8") as config_file:
            if path.suffix.lower() == ".json":
                loaded = json.load(config_file)
            else:
                loaded = parse_key_value_config(config_file.read())
    else:
        loaded = {}
        if create:
            save_config(DEFAULT_CONFIG, path)

    config = copy.deepcopy(DEFAULT_CONFIG)
    config.update(loaded)
    return normalize_config_paths(config)


def save_config(config: dict, path: str | Path | None = None):
    path = Path(path) if path else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    to_write = copy.deepcopy(DEFAULT_CONFIG)
    to_write.update(config)
    to_write = portable_config_for_save(to_write)
    with path.open("w", encoding="utf-8") as config_file:
        json.dump(to_write, config_file, indent=2)
        config_file.write("\n")


def portable_config_for_save(config: dict) -> dict:
    portable = copy.deepcopy(config)
    for key in PROJECT_PATH_KEYS:
        if portable.get(key):
            portable[key] = make_project_relative(portable[key])

    if portable.get("mega_mount_point"):
        portable["mega_mount_point"] = make_home_relative(portable["mega_mount_point"])

    if portable.get("media_root"):
        portable["media_root"] = make_project_relative(portable["media_root"])

    return portable


def make_project_relative(path_value: str | Path) -> str:
    path = Path(os.path.expandvars(os.path.expanduser(str(path_value))))
    if not path.is_absolute():
        return str(path)
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def make_home_relative(path_value: str | Path) -> str:
    path = Path(os.path.expandvars(os.path.expanduser(str(path_value))))
    home = Path.home()
    try:
        return str(Path("~") / path.relative_to(home))
    except ValueError:
        return str(path_value)


def ensure_config_file(path: str | Path | None = None) -> Path:
    path = Path(path) if path else config_path()
    if not path.exists():
        save_config(DEFAULT_CONFIG, path)
    return path


def resolve_project_path(path_value: str | Path) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(str(path_value))))
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def resolve_media_path(path_value: str | Path, config: dict | None = None) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(str(path_value))))
    if path.is_absolute():
        return path

    config = config or load_config()
    media_root = config.get("media_root")
    if media_root:
        return Path(media_root) / path
    return PROJECT_ROOT / path


def normalize_config_paths(config: dict) -> dict:
    normalized = copy.deepcopy(config)
    for key in PROJECT_PATH_KEYS:
        if normalized.get(key):
            normalized[key] = str(resolve_project_path(normalized[key]))

    if normalized.get("media_root"):
        normalized["media_root"] = str(resolve_project_path(normalized["media_root"]))

    if normalized.get("mega_mount_point"):
        normalized["mega_mount_point"] = str(
            Path(os.path.expandvars(os.path.expanduser(normalized["mega_mount_point"])))
        )

    return normalized


def normalize_station_config(station_config: dict, server_config: dict) -> dict:
    normalized = copy.deepcopy(station_config)

    if normalized.get("content_dir"):
        normalized["content_dir"] = str(resolve_media_path(normalized["content_dir"], server_config))

    for key in STATION_PROJECT_PATH_KEYS:
        if normalized.get(key):
            if isinstance(normalized[key], list):
                normalized[key] = [str(resolve_project_path(path)) for path in normalized[key]]
            else:
                normalized[key] = str(resolve_project_path(normalized[key]))

    if "images" in normalized and isinstance(normalized["images"], list):
        normalized["images"] = [str(resolve_project_path(path)) for path in normalized["images"]]

    return normalized


def day_parts_to_ranges(day_parts: dict) -> dict:
    converted = {}
    for key, part in day_parts.items():
        if isinstance(part, range):
            converted[key] = part
            continue
        if isinstance(part, list):
            converted[key] = part
            continue

        start_hour = part["start_hour"]
        end_hour = part["end_hour"]
        if end_hour > start_hour:
            converted[key] = range(start_hour, end_hour)
            continue

        hours = []
        hour = start_hour
        while hour <= 23:
            hours.append(hour)
            hour += 1
        hour = 0
        while hour <= end_hour:
            hours.append(hour)
            hour += 1
        converted[key] = hours
    return converted


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def resolve_window_geometry(server_conf: dict) -> dict:
    """Shared fullscreen/width/height/x/y resolution for every window FS42
    opens (mpv, guide, web, OSD overlays) so they can be kept in sync."""
    fullscreen = bool(server_conf.get("fullscreen", True))
    geometry = {"fullscreen": fullscreen, "combined_window": bool(server_conf.get("combined_window", True))}
    if not fullscreen:
        geometry["width"] = _safe_int(server_conf.get("window_width", 1280), 1280)
        geometry["height"] = _safe_int(server_conf.get("window_height", 720), 720)
        if geometry["combined_window"]:
            geometry["x"] = _safe_int(server_conf.get("window_x", 80), 80)
            geometry["y"] = _safe_int(server_conf.get("window_y", 60), 60)
    return geometry


def apply_cli_overrides(config: dict, args) -> dict:
    updated = dict(config)
    if getattr(args, "windowed", False):
        updated["fullscreen"] = False
    if getattr(args, "fullscreen", False):
        updated["fullscreen"] = True
    if getattr(args, "window_width", None):
        updated["window_width"] = args.window_width
    if getattr(args, "window_height", None):
        updated["window_height"] = args.window_height
    if getattr(args, "window_x", None) is not None:
        updated["window_x"] = args.window_x
    if getattr(args, "window_y", None) is not None:
        updated["window_y"] = args.window_y
    if getattr(args, "combined_window", None) is not None:
        updated["combined_window"] = args.combined_window
    if getattr(args, "direct_start_seek", False):
        updated["mpv_direct_start_seek"] = True
    return updated
