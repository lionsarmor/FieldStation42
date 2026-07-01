import datetime
import json
import sqlite3

from fs42.channel_validator import (
    ValidationReport,
    validate_catalog,
    validate_schedule,
    validate_station_paths,
)


def test_web_channels_do_not_require_local_media_catalogs_or_schedules():
    station = {
        "network_name": "The Weather Channel",
        "channel_number": 36,
        "network_type": "web",
        "web_url": "https://weather.com/retro/",
    }
    report = ValidationReport()

    validate_station_paths(station, report)
    validate_catalog(station, report)
    validate_schedule(station, report)

    messages = {issue.message for issue in report.errors}
    assert "Missing content_dir." not in messages
    assert "Missing catalog_path." not in messages
    assert "Missing schedule_path." not in messages
    assert not report.errors


def test_database_backed_catalogs_and_schedules_validate(tmp_path):
    db_path = tmp_path / "fs42_fluid.db"
    media_path = tmp_path / "episode.mp4"
    media_path.write_bytes(b"not a real video, but enough for path validation")

    with sqlite3.connect(db_path) as connection:
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE catalog_entries (station TEXT NOT NULL)")
        cursor.execute("INSERT INTO catalog_entries (station) VALUES (?)", ("DB TV",))
        cursor.execute(
            """
            CREATE TABLE liquid_blocks (
                station TEXT NOT NULL,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                plan_json TEXT
            )
            """
        )
        cursor.execute(
            "INSERT INTO liquid_blocks (station, start_time, end_time, plan_json) VALUES (?, ?, ?, ?)",
            (
                "DB TV",
                datetime.datetime(2026, 7, 1, 0, 0, 0),
                datetime.datetime(2026, 7, 1, 1, 0, 0),
                json.dumps([{"path": str(media_path), "duration": 3600, "is_stream": False}]),
            ),
        )

    station = {
        "network_name": "DB TV",
        "network_type": "standard",
        "_server_config": {"db_path": str(db_path)},
    }
    report = ValidationReport()

    validate_catalog(station, report)
    validate_schedule(station, report)

    assert not report.errors
