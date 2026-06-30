import argparse
import json
import logging
import os
from pathlib import Path

from fs42.config import PROJECT_ROOT, load_config, resolve_project_path


MEDIA_EXTENSIONS = {".mp4", ".mpg", ".mpeg", ".avi", ".mov", ".mkv", ".ts", ".m4v", ".webm", ".wmv"}
IGNORED_CONTENT_DIRS = {"bump", "commercial", "commercials", "signoff"}
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def media_root(config: dict | None = None) -> Path:
    config = config or load_config()
    if config.get("media_root"):
        return Path(config["media_root"]).expanduser()
    return Path(config.get("mega_mount_point", "~/mega")).expanduser() / "FS42_MEDIA"


def media_link_config_files() -> list[Path]:
    configs = []
    for path in sorted((PROJECT_ROOT / "confs").glob("*.json")):
        if path.name == "main_config.json":
            continue
        try:
            with path.open("r", encoding="utf-8") as fp:
                station = json.load(fp).get("station_conf", {})
        except (OSError, json.JSONDecodeError):
            continue
        if station.get("_media_link"):
            configs.append(path)
    return configs


def has_media(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    for item in path.rglob("*"):
        if item.is_file() and item.suffix.lower() in MEDIA_EXTENSIONS:
            return True
    return False


def humanize_slug(slug: str) -> str:
    special = {
        "90stv": "90s TV",
        "gak": "GAK",
        "scifiworld": "Sci-Fi World",
        "scifimovies": "Sci-Fi Movies",
    }
    if slug in special:
        return special[slug]
    return slug.replace("_", " ").replace("-", " ").title()


def relative_to_media_root(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def safe_symlink(source: Path, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        if destination.resolve() == source.resolve():
            return
        destination.unlink()
    elif destination.exists():
        logging.getLogger("media_links").warning(
            "Not replacing non-symlink path: %s", destination
        )
        return
    destination.symlink_to(source, target_is_directory=source.is_dir())


def schedule_for_tags(tags: list[str]) -> dict:
    if len(tags) == 1:
        slot = {"tags": tags[0]}
    else:
        slot = {"tags": tags, "random_tags": True}
    return {day: {str(hour): dict(slot) for hour in range(24)} for day in DAYS}


def discover_channel(channel_dir: Path, root: Path, channel_number: int) -> dict | None:
    slug = channel_dir.name
    content_sources = []

    for child in sorted(channel_dir.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir():
            continue
        if child.name.lower() in IGNORED_CONTENT_DIRS:
            continue
        if has_media(child):
            content_sources.append(child)

    if not content_sources:
        return None

    bump_source = channel_dir / "bump"
    if not has_media(bump_source):
        bump_source = root / "Bumps"

    commercial_source = channel_dir / "commercial"
    if not has_media(commercial_source):
        alternate = channel_dir / "commercials"
        commercial_source = alternate if has_media(alternate) else root / "Commercials"

    tags = [source.name for source in content_sources]
    station = {
        "network_name": humanize_slug(slug),
        "network_long_name": humanize_slug(slug),
        "channel_number": channel_number,
        "network_type": "standard",
        "content_dir": f"catalog/{slug}",
        "commercial_dir": "commercial",
        "bump_dir": "bump",
        "catalog_path": f"runtime/catalogs/{slug}.pkl",
        "schedule_path": f"runtime/schedules/{slug}.pkl",
        "break_duration": 120,
        "commercial_free": False,
        "_media_link": {
            "slug": slug,
            "content_sources": [relative_to_media_root(source, root) for source in content_sources],
            "bump_source": relative_to_media_root(bump_source, root),
            "commercial_source": relative_to_media_root(commercial_source, root),
        },
    }
    station.update(schedule_for_tags(tags))
    return {"station_conf": station}


def discover_channels(config: dict | None = None, start_channel: int = 42, write: bool = False) -> list[dict]:
    config = config or load_config()
    root = media_root(config)
    channels_root = root / "Channels"
    if not channels_root.exists():
        raise FileNotFoundError(f"MEGA Channels folder not found: {channels_root}")

    configs = []
    channel_number = start_channel
    for channel_dir in sorted(channels_root.iterdir(), key=lambda item: item.name.lower()):
        if not channel_dir.is_dir():
            continue
        station_config = discover_channel(channel_dir, root, channel_number)
        if station_config is None:
            continue
        configs.append(station_config)
        if write:
            write_station_config(station_config)
        channel_number += 1
    return configs


def write_station_config(station_config: dict):
    slug = station_config["station_conf"]["_media_link"]["slug"]
    path = PROJECT_ROOT / "confs" / f"{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as config_file:
        json.dump(station_config, config_file, indent=2)
        config_file.write("\n")


def sync_links_from_configs(config: dict | None = None) -> int:
    config = config or load_config()
    root = media_root(config)
    count = 0
    logger = logging.getLogger("media_links")

    for config_file in media_link_config_files():
        with config_file.open("r", encoding="utf-8") as fp:
            station = json.load(fp)["station_conf"]

        media_link = station.get("_media_link")
        if not media_link:
            continue

        link_root = resolve_project_path(station["content_dir"])
        link_root.mkdir(parents=True, exist_ok=True)

        for source_value in media_link.get("content_sources", []):
            source = root / source_value
            if not source.exists():
                logger.warning("Content source missing: %s", source)
                continue
            safe_symlink(source, link_root / source.name)
            count += 1

        bump_source = root / media_link["bump_source"]
        commercial_source = root / media_link["commercial_source"]
        if bump_source.exists():
            safe_symlink(bump_source, link_root / station["bump_dir"])
            count += 1
        else:
            logger.warning("Bump source missing: %s", bump_source)

        if commercial_source.exists():
            safe_symlink(commercial_source, link_root / station["commercial_dir"])
            count += 1
        else:
            logger.warning("Commercial source missing: %s", commercial_source)

    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover MEGA channel folders and sync local FS42 media links.")
    parser.add_argument("--discover", action="store_true", help="Write channel configs from MEGA Channels.")
    parser.add_argument("--sync", action="store_true", help="Create/update local symlinks from channel configs.")
    parser.add_argument("--start-channel", type=int, default=42, help="First channel number.")
    args = parser.parse_args()

    logging.basicConfig(format="%(levelname)s:%(name)s:%(message)s", level=logging.INFO)

    if args.discover:
        configs = discover_channels(start_channel=args.start_channel, write=True)
        print(f"Wrote {len(configs)} channel config(s).")

    if args.sync:
        count = sync_links_from_configs()
        print(f"Synced {count} media link(s).")

    if not args.discover and not args.sync:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
