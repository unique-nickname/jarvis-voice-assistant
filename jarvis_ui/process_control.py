"""Find and stop other Jarvis processes from this checkout."""

from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from core.config import PROJECT_ROOT


_ENTRYPOINTS = {
    "jarvis_ui.launcher",
    "jarvis_ui.settings",
    "main",
    "voice.assistant_loop",
    "voice.tts_worker",
}
_SCRIPT_ENTRYPOINTS = {
    PROJECT_ROOT / "main.py": "main",
    PROJECT_ROOT / "voice" / "assistant_loop.py": "voice.assistant_loop",
}


@dataclass(frozen=True)
class JarvisProcess:
    pid: int
    module: str
    start_time: int


def _read_start_time(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as process_file:
            stat_fields = process_file.read()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None

    closing_parenthesis = stat_fields.rfind(")")
    if closing_parenthesis == -1:
        return None
    remaining_fields = stat_fields[closing_parenthesis + 2 :].split()
    if not remaining_fields or remaining_fields[0] in {"Z", "X"}:
        return None
    try:
        # The remaining fields start at stat field 3; starttime is field 22.
        return int(remaining_fields[19])
    except (IndexError, ValueError):
        return None


def _module_from_command(command: list[str]) -> str | None:
    for index, argument in enumerate(command[:-1]):
        if argument == "-m" and command[index + 1] in _ENTRYPOINTS:
            return command[index + 1]
    for argument in command[1:]:
        try:
            script = Path(argument)
            if not script.is_absolute():
                script = PROJECT_ROOT / script
            script = script.resolve()
        except (OSError, RuntimeError):
            continue
        module = _SCRIPT_ENTRYPOINTS.get(script)
        if module is not None:
            return module
    return None


def _find_other_jarvis_processes() -> list[JarvisProcess]:
    processes = []
    current_pid = os.getpid()
    current_uid = os.getuid()

    try:
        entries = os.scandir("/proc")
    except OSError:
        return processes

    with entries:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == current_pid:
                continue

            try:
                if entry.stat(follow_symlinks=False).st_uid != current_uid:
                    continue
                command_path = f"/proc/{pid}/cmdline"
                with open(command_path, "rb") as command_file:
                    command = [
                        os.fsdecode(argument)
                        for argument in command_file.read().split(b"\0")
                        if argument
                    ]
                module = _module_from_command(command)
                if module is None:
                    continue
                process_cwd = Path(os.readlink(f"/proc/{pid}/cwd")).resolve()
                if process_cwd != PROJECT_ROOT:
                    continue
                start_time = _read_start_time(pid)
                if start_time is not None:
                    processes.append(JarvisProcess(pid, module, start_time))
            except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
                continue

    return processes


def _is_running(process: JarvisProcess) -> bool:
    return _read_start_time(process.pid) == process.start_time


def _signal(process: JarvisProcess, requested_signal: int) -> None:
    if not _is_running(process):
        return
    try:
        os.kill(process.pid, requested_signal)
    except (ProcessLookupError, PermissionError):
        pass


def _wait_for_exit(processes: list[JarvisProcess], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_is_running(process) for process in processes):
            return
        time.sleep(0.1)


def stop_existing_jarvis_processes() -> tuple[int, list[int]]:
    """Stop other Jarvis entrypoints from this checkout; return count and survivors."""
    processes = _find_other_jarvis_processes()
    if not processes:
        return 0, []

    assistants = [
        process
        for process in processes
        if process.module == "voice.assistant_loop"
    ]
    for process in assistants:
        _signal(process, signal.SIGINT)
    _wait_for_exit(assistants, timeout=15)

    remaining = [process for process in processes if _is_running(process)]
    for process in remaining:
        _signal(process, signal.SIGTERM)
    _wait_for_exit(remaining, timeout=2)

    remaining = [process for process in processes if _is_running(process)]
    for process in remaining:
        _signal(process, signal.SIGKILL)
    _wait_for_exit(remaining, timeout=1)

    survivors = [process.pid for process in processes if _is_running(process)]
    return len(processes), survivors
