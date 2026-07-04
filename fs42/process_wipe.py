import logging
import os
import signal
import subprocess
import time
from pathlib import Path

from fs42.config import PROJECT_ROOT


_COMPANION_UNITS = (
    "fs42-osd.service",
    "fs42-cable-box.service",
)
_PLAYER_UNIT = "fs42.service"
_REMOTE_UNIT = "fs42-remote-controller.service"

_SCRIPT_MARKERS = (
    "field_player.py",
    "fs42/osd/main.py",
    "fs42/pi/cable_box.py",
    "fs42/webrender/web_render.py",
    "fs42/guide_tk.py",
)
_REMOTE_MARKER = "fs42/pi/remote_controller.py"
_PROJECT_ROOT = PROJECT_ROOT.resolve()


def stop_systemd_companion_units(include_remote=False, include_player=False, logger=None):
    """Best-effort stop for user services that can restart FS42 windows."""
    units = list(_COMPANION_UNITS)
    if include_player:
        units.insert(0, _PLAYER_UNIT)
    if include_remote:
        units.append(_REMOTE_UNIT)

    try:
        subprocess.run(
            ["systemctl", "--user", "stop", *units],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except Exception as exc:
        _log(logger, logging.DEBUG, "Could not stop FS42 companion systemd units: %s", exc)


def wipe_runtime_processes(
    include_remote=False,
    stop_units=False,
    stop_player_unit=False,
    grace_seconds=1.0,
    logger=None,
):
    """Terminate known FieldStation42 runtime processes for this checkout.

    This is intentionally narrower than a blanket `pkill`: candidates must be
    known FS42 scripts, mpv with the FS42 IPC socket, or helper processes whose
    cwd is this project directory.
    """
    if stop_units:
        stop_systemd_companion_units(
            include_remote=include_remote,
            include_player=stop_player_unit,
            logger=logger,
        )

    protected_pids = {os.getpid(), os.getppid()}
    pids = _candidate_pids(include_remote=include_remote, protected_pids=protected_pids)
    if not pids:
        return []

    _signal_pids(pids, signal.SIGTERM, logger)
    deadline = time.time() + grace_seconds
    while time.time() < deadline and any(_pid_exists(pid) for pid in pids):
        time.sleep(0.05)

    lingering = [pid for pid in pids if _pid_exists(pid)]
    if lingering:
        _signal_pids(lingering, signal.SIGKILL, logger)

    return pids


def _candidate_pids(include_remote, protected_pids):
    pids = []
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue

        pid = int(proc_dir.name)
        if pid in protected_pids:
            continue

        if _is_fs42_runtime_process(pid, include_remote=include_remote):
            pids.append(pid)

    return pids


def _is_fs42_runtime_process(pid, include_remote):
    cmdline = _read_cmdline(pid)
    if not cmdline:
        return False

    normalized = cmdline.replace("\\", "/")
    markers = list(_SCRIPT_MARKERS)
    if include_remote:
        markers.append(_REMOTE_MARKER)

    if any(marker in normalized for marker in markers):
        return True

    if "/tmp/mpvsocket" in normalized:
        return True

    command_name = _read_comm(pid)
    if command_name in {"mpv", "QtWebEngineProcess"} and _cwd_is_project(pid):
        return True

    return False


def _read_cmdline(pid):
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", errors="ignore").strip()


def _read_comm(pid):
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _cwd_is_project(pid):
    try:
        cwd = Path(os.readlink(f"/proc/{pid}/cwd")).resolve()
    except OSError:
        return False
    return cwd == _PROJECT_ROOT or _PROJECT_ROOT in cwd.parents


def _signal_pids(pids, sig, logger):
    for pid in pids:
        try:
            os.kill(pid, sig)
            _log(logger, logging.INFO, "Sent %s to FS42 runtime process %s", sig.name, pid)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            _log(logger, logging.WARNING, "No permission to signal FS42 runtime process %s: %s", pid, exc)


def _pid_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _log(logger, level, message, *args):
    if logger is None:
        logger = logging.getLogger("ProcessWipe")
    logger.log(level, message, *args)
