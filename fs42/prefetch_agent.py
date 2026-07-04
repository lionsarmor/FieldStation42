import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fs42.config import resolve_media_path, resolve_project_path
from fs42.autobump_agent import AutoBumpAgent

_SIZE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([KMGkmg]?)\s*$")
_SIZE_MULTIPLIERS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def parse_size(value, default):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return max(0, int(value))
    match = _SIZE_RE.match(str(value))
    if not match:
        return default
    amount, suffix = match.groups()
    return int(float(amount) * _SIZE_MULTIPLIERS[suffix.lower()])


class PrefetchAgent:
    """Warms the rclone/Mega VFS cache for content that is about to air.

    Reads segments a channel change would need (the currently tuned channel's
    upcoming plan entries, plus optionally neighboring channels' current
    entries) and touches those byte ranges so they're already in rclone's
    local cache by the time a viewer lands on them.
    """

    # After a channel change, mpv is racing to open the new file - never make
    # it compete with our own background reads for rclone transfer slots.
    POST_CHANGE_COOLDOWN_SECONDS = 4.0

    def __init__(self, server_conf, get_stations_fn, get_channel_index_fn, get_changed_at_fn=None):
        self._l = logging.getLogger("PrefetchAgent")
        self.enabled = bool(server_conf.get("media_prefetch_enabled", False))
        self.prefetch_bytes = parse_size(server_conf.get("media_prefetch_bytes"), 16 * 1024 * 1024)
        self.chunk_size = max(64 * 1024, parse_size(server_conf.get("media_prefetch_chunk_size"), 4 * 1024 * 1024))
        self.workers = max(1, int(server_conf.get("media_prefetch_workers", 1) or 1))
        self.entries = max(1, int(server_conf.get("media_prefetch_entries", 1) or 1))
        self.neighbor_channels = max(0, int(server_conf.get("media_prefetch_neighbor_channels", 0) or 0))
        self.min_interval = max(0.0, float(server_conf.get("media_prefetch_min_interval", 180) or 0))
        self.delay_seconds = max(1.0, float(server_conf.get("media_prefetch_delay_seconds", 5) or 1))
        self.server_conf = server_conf
        self.status_socket = server_conf.get("status_socket")

        self._get_stations_fn = get_stations_fn
        self._get_channel_index_fn = get_channel_index_fn
        self._get_changed_at_fn = get_changed_at_fn or (lambda: 0)

        self._last_warmed = {}
        self._warmed_lock = threading.Lock()
        self._executor = None
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if not self.enabled:
            self._l.info("Media prefetch disabled (media_prefetch_enabled=false)")
            return
        self._executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="prefetch")
        self._thread = threading.Thread(target=self._run_loop, name="PrefetchAgent", daemon=True)
        self._thread.start()
        self._l.info(
            f"Prefetch agent started: bytes={self.prefetch_bytes} chunk={self.chunk_size} "
            f"workers={self.workers} entries={self.entries} neighbors={self.neighbor_channels} "
            f"min_interval={self.min_interval}s delay={self.delay_seconds}s"
        )

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._executor:
            self._executor.shutdown(wait=False)

    def _run_loop(self):
        while not self._stop.is_set():
            try:
                since_change = time.time() - self._get_changed_at_fn()
                if since_change < self.POST_CHANGE_COOLDOWN_SECONDS:
                    self._l.debug(
                        f"Skipping cycle, {since_change:.1f}s since last channel change "
                        f"(cooldown={self.POST_CHANGE_COOLDOWN_SECONDS}s)"
                    )
                else:
                    self._prefetch_cycle()
            except Exception as e:
                self._l.warning(f"Prefetch cycle failed: {e}")
            self._stop.wait(self.delay_seconds)

    def _currently_playing_path(self):
        if not self.status_socket:
            return None
        try:
            with open(self.status_socket, "r") as fp:
                contents = fp.read()
            if not contents:
                return None
            status = json.loads(contents)
            file_path = status.get("file_path")
            return str(Path(file_path).expanduser()) if file_path else None
        except Exception:
            return None

    def _candidate_indices(self):
        stations = self._get_stations_fn()
        if not stations:
            return []
        count = len(stations)
        current = self._get_channel_index_fn() % count
        indices = [current]
        for distance in range(1, self.neighbor_channels + 1):
            indices.append((current + distance) % count)
            indices.append((current - distance) % count)
        # de-dupe while preserving order
        seen = set()
        ordered = []
        for idx in indices:
            if idx not in seen:
                seen.add(idx)
                ordered.append(idx)
        return [(idx, stations[idx]) for idx in ordered]

    def _prefetch_cycle(self):
        import datetime
        from fs42.liquid_manager import LiquidManager, ScheduleNotFound, ScheduleQueryNotInBounds

        liquid = LiquidManager()
        now = datetime.datetime.now()
        active_path = self._currently_playing_path()

        for _idx, station in self._candidate_indices():
            if self._stop.is_set():
                return
            if not station.get("_has_schedule", False):
                continue

            network_name = station["network_name"]
            try:
                play_point = liquid.get_play_point(network_name, now)
            except (ScheduleNotFound, ScheduleQueryNotInBounds):
                continue
            except Exception as e:
                self._l.debug(f"Skipping {network_name}, could not get play point: {e}")
                continue

            if play_point is None:
                continue

            upcoming = play_point.plan[play_point.index : play_point.index + self.entries]
            for offset_idx, entry in enumerate(upcoming):
                if getattr(entry, "is_stream", False):
                    continue
                if AutoBumpAgent.is_autobump_url(entry.path):
                    continue

                # only the first entry (the one live right now) needs a mid-file
                # seek estimate; anything queued after it starts at byte 0.
                seconds_offset = play_point.offset if offset_idx == 0 else 0
                self._schedule_warm(entry.path, entry.duration, seconds_offset, active_path)

    def _schedule_warm(self, raw_path, duration, seconds_offset, active_path=None):
        resolved = self._resolve_path(raw_path)
        if resolved is None:
            return

        key = str(resolved)
        if active_path and key == active_path:
            # mpv already has this file open and streaming - reading it
            # ourselves would only compete for the same rclone transfer slots.
            return
        now = time.time()
        with self._warmed_lock:
            last = self._last_warmed.get(key, 0)
            if now - last < self.min_interval:
                return
            self._last_warmed[key] = now

        self._executor.submit(self._do_warm, resolved, duration, seconds_offset)

    def _resolve_path(self, raw_path):
        try:
            if os.path.exists(raw_path):
                return Path(raw_path).expanduser()
            project_candidate = resolve_project_path(raw_path)
            if project_candidate.exists():
                return project_candidate
            media_candidate = resolve_media_path(raw_path, self.server_conf)
            if media_candidate.exists():
                return media_candidate
        except Exception as e:
            self._l.debug(f"Could not resolve prefetch path {raw_path}: {e}")
        return None

    def _do_warm(self, resolved_path, duration, seconds_offset):
        try:
            file_size = os.path.getsize(resolved_path)
        except OSError as e:
            self._l.debug(f"Prefetch stat failed for {resolved_path}: {e}")
            return

        byte_offset = 0
        if seconds_offset and duration and duration > 0:
            # rough proportional estimate of where in the file playback would
            # resume - good enough to land near the right region for warming
            byte_offset = int(file_size * (seconds_offset / duration))
        byte_offset = max(0, min(byte_offset, max(0, file_size - 1)))

        start = time.time()
        read_total = 0
        try:
            with open(resolved_path, "rb") as fp:
                fp.seek(byte_offset)
                remaining = self.prefetch_bytes
                while remaining > 0 and not self._stop.is_set():
                    chunk = fp.read(min(self.chunk_size, remaining))
                    if not chunk:
                        break
                    read_total += len(chunk)
                    remaining -= len(chunk)
            self._l.debug(
                f"Warmed {resolved_path} offset={byte_offset} bytes={read_total} "
                f"in {time.time() - start:.2f}s"
            )
        except Exception as e:
            self._l.debug(f"Prefetch warm failed for {resolved_path}: {e}")
