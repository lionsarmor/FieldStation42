import argparse
import datetime
import hashlib
import json
import logging
import shutil
import sqlite3
import subprocess
from pathlib import Path

from fs42.config import PROJECT_ROOT, load_config, resolve_project_path
from fs42.mega import rclone_available


MANIFEST_NAME = "compiled_manifest.json"
MANIFEST_VERSION = 1


class CompiledSyncError(RuntimeError):
    pass


def runtime_path(relative_path: str) -> Path:
    return resolve_project_path(relative_path)


def local_manifest_path() -> Path:
    return runtime_path(f"runtime/{MANIFEST_NAME}")


def remote_base(config: dict | None = None) -> str:
    config = config or load_config()
    remote = config.get("mega_remote")
    if not remote:
        raise CompiledSyncError("mega_remote is not configured.")
    remote = remote.rstrip(":")
    remote_path = (config.get("compiled_remote_path") or "FS42_MEDIA/Compiled").strip("/")
    return f"{remote}:{remote_path}"


def remote_join(base: str, *parts: str) -> str:
    clean_parts = [part.strip("/") for part in parts if part]
    if not clean_parts:
        return base
    return f"{base}/{'/'.join(clean_parts)}"


def run_rclone(args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    if not rclone_available():
        raise CompiledSyncError("rclone is not installed or is not on PATH.")
    result = subprocess.run(
        ["rclone", *args],
        check=False,
        capture_output=capture,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() if result.stderr else result.stdout.strip()
        raise CompiledSyncError(message or f"rclone {' '.join(args)} failed.")
    return result


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def catalog_files() -> list[Path]:
    return sorted(runtime_path("runtime/catalogs").glob("*.pkl"))


def schedule_files() -> list[Path]:
    return sorted(runtime_path("runtime/schedules").glob("*.pkl"))


def cache_db_path() -> Path:
    return runtime_path("runtime/fs42_fluid.db")


def _db_table_count(db_path: Path, table_name: str) -> int:
    if table_name not in {"catalog_entries", "liquid_blocks"}:
        return 0
    if not db_path.exists():
        return 0
    try:
        with sqlite3.connect(db_path) as connection:
            cursor = connection.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row = cursor.fetchone()
    except sqlite3.Error:
        return 0
    return int(row[0] if row else 0)


def compiled_db_counts(config: dict | None = None) -> dict:
    config = config or load_config()
    db_path = Path(config.get("db_path") or cache_db_path())
    return {
        "catalog_entries": _db_table_count(db_path, "catalog_entries"),
        "schedule_blocks": _db_table_count(db_path, "liquid_blocks"),
    }


def has_db_compiled_state(config: dict | None = None) -> bool:
    counts = compiled_db_counts(config)
    return counts["catalog_entries"] > 0 and counts["schedule_blocks"] > 0


def compiled_files() -> list[Path]:
    candidates = []
    candidates.extend(catalog_files())
    candidates.extend(schedule_files())
    db_path = cache_db_path()
    if db_path.exists():
        candidates.append(db_path)
    return [path for path in candidates if path.is_file()]


def relative_runtime_path(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT))


def build_manifest() -> dict:
    files = []
    for path in compiled_files():
        stat = path.stat()
        files.append(
            {
                "path": relative_runtime_path(path),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "sha256": file_sha256(path),
            }
        )

    return {
        "manifest_version": MANIFEST_VERSION,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "files": files,
    }


def save_local_manifest(manifest: dict) -> Path:
    path = local_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2)
        fp.write("\n")
    return path


def load_local_manifest() -> dict | None:
    path = local_manifest_path()
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def load_remote_manifest(config: dict | None = None) -> dict | None:
    base = remote_base(config)
    try:
        result = run_rclone(["cat", remote_join(base, MANIFEST_NAME)], capture=True)
    except CompiledSyncError:
        return None
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)


def manifest_created_at(manifest: dict | None) -> datetime.datetime | None:
    if not manifest:
        return None
    created_at = manifest.get("created_at")
    if not created_at:
        return None
    return datetime.datetime.fromisoformat(created_at)


def local_files_match_manifest(manifest: dict) -> bool:
    for entry in manifest.get("files", []):
        path = runtime_path(entry["path"])
        if not path.exists() or not path.is_file():
            return False
        stat = path.stat()
        if stat.st_size != entry.get("size"):
            return False
        if file_sha256(path) != entry.get("sha256"):
            return False
    return True


def has_local_compiled_files() -> bool:
    return bool(catalog_files() or schedule_files() or has_db_compiled_state())


def upload_compiled(config: dict | None = None) -> dict:
    config = config or load_config()
    db_counts = compiled_db_counts(config)
    if not catalog_files() and db_counts["catalog_entries"] <= 0:
        raise CompiledSyncError("No compiled catalog data was found. Run env/bin/python station_42.py --rebuild_catalog first.")
    if not schedule_files() and db_counts["schedule_blocks"] <= 0:
        raise CompiledSyncError("No compiled schedule data was found. Run env/bin/python station_42.py --add_day first.")

    manifest = build_manifest()
    if not manifest["files"]:
        raise CompiledSyncError("No compiled catalogs, schedules, or cache DB were found to upload.")

    manifest_path = save_local_manifest(manifest)
    base = remote_base(config)
    logger = logging.getLogger("compiled_sync")

    run_rclone(["mkdir", base])
    for relative_dir in ("runtime/catalogs", "runtime/schedules"):
        source = runtime_path(relative_dir)
        if source.exists():
            destination = remote_join(base, relative_dir)
            logger.info("Uploading %s to %s", source, destination)
            run_rclone(["copy", str(source), destination])

    db_path = cache_db_path()
    if db_path.exists():
        run_rclone(["copyto", str(db_path), remote_join(base, "runtime/fs42_fluid.db"), "--ignore-times"])

    run_rclone(["copyto", str(manifest_path), remote_join(base, MANIFEST_NAME), "--ignore-times"])
    return manifest


def should_download(remote_manifest: dict | None, force: bool = False) -> tuple[bool, str]:
    if remote_manifest is None:
        return False, "No remote compiled manifest found."
    if force:
        return True, "Forced compiled sync requested."

    local_manifest = load_local_manifest()
    if local_manifest:
        remote_time = manifest_created_at(remote_manifest)
        local_time = manifest_created_at(local_manifest)
        if remote_time and local_time and remote_time <= local_time and local_files_match_manifest(local_manifest):
            return False, "Local compiled files are already current."
        return True, "Remote compiled files are newer or local files changed."

    if has_local_compiled_files():
        return False, "Local compiled files exist but have no manifest; use --force-sync-compiled to replace them."

    return True, "No local compiled files found."


def download_compiled(config: dict | None = None, force: bool = False) -> tuple[bool, str]:
    config = config or load_config()
    remote_manifest = load_remote_manifest(config)
    should_sync, reason = should_download(remote_manifest, force=force)
    if not should_sync:
        return False, reason

    base = remote_base(config)
    remote_files = {entry["path"] for entry in remote_manifest.get("files", [])}
    for relative_dir in ("runtime/catalogs", "runtime/schedules"):
        if not any(path.startswith(f"{relative_dir}/") for path in remote_files):
            continue
        destination = runtime_path(relative_dir)
        destination.mkdir(parents=True, exist_ok=True)
        run_rclone(["copy", remote_join(base, relative_dir), str(destination)])

    if "runtime/fs42_fluid.db" in remote_files:
        run_rclone(["copyto", remote_join(base, "runtime/fs42_fluid.db"), str(runtime_path("runtime/fs42_fluid.db"))])

    manifest_destination = local_manifest_path()
    run_rclone(["copyto", remote_join(base, MANIFEST_NAME), str(manifest_destination)])
    return True, reason


def compiled_status(config: dict | None = None) -> dict:
    config = config or load_config()
    local_manifest = load_local_manifest()
    remote_manifest = load_remote_manifest(config)
    db_counts = compiled_db_counts(config)
    return {
        "local_files": len(compiled_files()),
        "local_catalogs": len(catalog_files()),
        "local_schedules": len(schedule_files()),
        "local_db": cache_db_path().exists(),
        "local_db_catalog_entries": db_counts["catalog_entries"],
        "local_db_schedule_blocks": db_counts["schedule_blocks"],
        "local_manifest": local_manifest,
        "remote_manifest": remote_manifest,
        "remote_base": remote_base(config),
    }


def print_status(status: dict):
    print(f"Remote compiled folder: {status['remote_base']}")
    print(f"Local compiled file count: {status['local_files']}")
    print(f"Local catalogs: {status['local_catalogs']}")
    print(f"Local schedules: {status['local_schedules']}")
    print(f"Local cache DB: {'present' if status['local_db'] else 'missing'}")
    print(f"Local DB catalog entries: {status['local_db_catalog_entries']}")
    print(f"Local DB schedule blocks: {status['local_db_schedule_blocks']}")
    local_manifest = status["local_manifest"]
    remote_manifest = status["remote_manifest"]
    if local_manifest:
        print(f"Local manifest: {local_manifest.get('created_at')} ({len(local_manifest.get('files', []))} files)")
    else:
        print("Local manifest: missing")
    if remote_manifest:
        print(f"Remote manifest: {remote_manifest.get('created_at')} ({len(remote_manifest.get('files', []))} files)")
    else:
        print("Remote manifest: missing")


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload/download compiled FS42 catalogs, schedules, and cache DB.")
    parser.add_argument("--upload", action="store_true", help="Upload local compiled files to MEGA.")
    parser.add_argument("--download", action="store_true", help="Download newer compiled files from MEGA.")
    parser.add_argument("--force", action="store_true", help="Replace local compiled files even if local files exist.")
    parser.add_argument("--status", action="store_true", help="Show local and remote compiled cache status.")
    args = parser.parse_args()

    logging.basicConfig(format="%(levelname)s:%(name)s:%(message)s", level=logging.INFO)

    try:
        if args.upload:
            manifest = upload_compiled()
            print(f"Uploaded {len(manifest['files'])} compiled file(s).")
        if args.download:
            changed, reason = download_compiled(force=args.force)
            print(("Downloaded compiled files. " if changed else "Skipped download. ") + reason)
        if args.status:
            print_status(compiled_status())
        if not args.upload and not args.download and not args.status:
            parser.print_help()
    except CompiledSyncError as exc:
        print(f"Compiled sync failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
