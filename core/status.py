"""Runtime status reporting for the desktop launcher and external widgets."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path


RUNTIME_DIRECTORY = Path.home() / ".local" / "state" / "jarvis"
STATUS_FILE = RUNTIME_DIRECTORY / "status.json"
RUNTIME_STATES = {
    "starting",
    "wake_word",
    "listening_command",
    "thinking",
    "executing",
    "waiting_approval",
    "speaking",
    "follow_up",
    "error",
    "stopped",
    "already_running",
    "stopping",
}


def _process_start_time(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as process_file:
            stat_fields = process_file.read()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None

    closing_parenthesis = stat_fields.rfind(")")
    if closing_parenthesis == -1:
        return None
    remaining_fields = stat_fields[closing_parenthesis + 2 :].split()
    try:
        # The remaining fields start at proc stat field 3; starttime is field 22.
        return int(remaining_fields[19])
    except (IndexError, ValueError):
        return None


def _write_runtime_status(state: str) -> None:
    temporary_path: Path | None = None
    try:
        RUNTIME_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_info = RUNTIME_DIRECTORY.lstat()
        if (
            not stat.S_ISDIR(directory_info.st_mode)
            or directory_info.st_uid != os.geteuid()
        ):
            return
        RUNTIME_DIRECTORY.chmod(0o700)

        try:
            status_info = STATUS_FILE.lstat()
        except FileNotFoundError:
            status_info = None
        if status_info is not None and (
            not stat.S_ISREG(status_info.st_mode)
            or status_info.st_uid != os.geteuid()
        ):
            return

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".status-",
            dir=RUNTIME_DIRECTORY,
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        payload = {
            "state": state,
            "pid": os.getpid(),
            "process_start_time": _process_start_time(os.getpid()),
            "updated_at": time.time(),
        }
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        with os.fdopen(descriptor, "wb") as status_file:
            status_file.write(encoded)
            status_file.flush()
            os.fsync(status_file.fileno())
        os.replace(temporary_path, STATUS_FILE)
        temporary_path = None
    except (OSError, ValueError, TypeError):
        # Status reporting must not interrupt assistant startup or shutdown.
        pass
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def emit_runtime_status(state: str, *, persist: bool = True) -> None:
    """Report one state to a supervising UI and to the private runtime file."""
    if state not in RUNTIME_STATES:
        return
    message = f"JARVIS_STATUS={state}\n".encode("ascii")
    descriptor = os.environ.get("JARVIS_STATUS_FD")
    if descriptor is not None:
        try:
            file_descriptor = int(descriptor)
            if file_descriptor >= 3:
                os.write(file_descriptor, message)
        except (OSError, ValueError):
            pass
    elif os.environ.get("JARVIS_STATUS_OUTPUT") == "1":
        print(message.decode("ascii"), end="", file=sys.stdout, flush=True)

    if persist:
        _write_runtime_status(state)


def read_runtime_status() -> str:
    """Return the last state, treating records from dead or reused PIDs as stopped."""
    try:
        directory_info = RUNTIME_DIRECTORY.lstat()
        if (
            not stat.S_ISDIR(directory_info.st_mode)
            or directory_info.st_uid != os.geteuid()
        ):
            return "stopped"
        status_info = STATUS_FILE.lstat()
        if (
            not stat.S_ISREG(status_info.st_mode)
            or status_info.st_uid != os.geteuid()
            or status_info.st_size > 4096
        ):
            return "stopped"
        with STATUS_FILE.open("r", encoding="utf-8") as status_file:
            record = json.load(status_file)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return "stopped"

    if not isinstance(record, dict):
        return "stopped"
    state = record.get("state")
    pid = record.get("pid")
    process_start_time = record.get("process_start_time")
    if not isinstance(state, str) or state not in RUNTIME_STATES:
        return "stopped"
    if state in {"stopped", "error"}:
        return state
    if type(pid) is not int or not 1 <= pid <= 2**31 - 1:
        return "stopped"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "stopped"
    except PermissionError:
        pass
    except (OSError, OverflowError):
        return "stopped"
    if (
        type(process_start_time) is int
        and _process_start_time(pid) != process_start_time
    ):
        return "stopped"
    return state
