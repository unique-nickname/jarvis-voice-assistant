"""In-process one-shot timers that notify through the desktop."""

from __future__ import annotations

import math
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from typing import Any


_MAX_ACTIVE_TIMERS = 10
_MAX_DURATION_SECONDS = 86_400


@dataclass
class _TimerEntry:
    timer_id: str
    label: str
    deadline: float
    expires_at: str
    timer: threading.Timer


class TimerService:
    """Manage temporary timers for one running Jarvis process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._timers: dict[str, _TimerEntry] = {}
        self._next_id = 1
        self._closed = False

    def create_timer(self, duration_seconds: int, label: str) -> dict[str, Any]:
        if (
            type(duration_seconds) is not int
            or not 1 <= duration_seconds <= _MAX_DURATION_SECONDS
        ):
            return {
                "success": False,
                "error": f"Timer duration must be between 1 and {_MAX_DURATION_SECONDS} seconds.",
            }
        if (
            not isinstance(label, str)
            or not label.strip()
            or len(label.strip()) > 120
            or any(ord(character) < 32 for character in label)
        ):
            return {
                "success": False,
                "error": "Timer label must be 1 to 120 plain-text characters.",
            }
        if shutil.which("notify-send") is None:
            return {"success": False, "error": "Desktop notifications require notify-send."}

        clean_label = label.strip()
        with self._lock:
            if self._closed:
                return {"success": False, "error": "Timer service is shutting down."}
            if len(self._timers) >= _MAX_ACTIVE_TIMERS:
                return {
                    "success": False,
                    "error": f"At most {_MAX_ACTIVE_TIMERS} timers can be active.",
                }

            timer_id = f"timer-{self._next_id}"
            self._next_id += 1
            deadline = time.monotonic() + duration_seconds
            expires_at = (
                datetime.now().astimezone() + timedelta(seconds=duration_seconds)
            ).isoformat(timespec="seconds")
            timer = threading.Timer(
                duration_seconds,
                self._notify_expiry,
                args=(timer_id,),
            )
            timer.daemon = True
            entry = _TimerEntry(timer_id, clean_label, deadline, expires_at, timer)
            self._timers[timer_id] = entry
            timer.start()

        return {
            "success": True,
            "timer_id": timer_id,
            "label": clean_label,
            "duration_seconds": duration_seconds,
            "expires_at": expires_at,
        }

    def list_timers(self) -> dict[str, Any]:
        with self._lock:
            timers = [
                {
                    "timer_id": entry.timer_id,
                    "label": entry.label,
                    "remaining_seconds": max(
                        0,
                        math.ceil(entry.deadline - time.monotonic()),
                    ),
                    "expires_at": entry.expires_at,
                }
                for entry in sorted(
                    self._timers.values(),
                    key=lambda item: item.deadline,
                )
            ]
        return {"success": True, "timers": timers}

    def cancel_timer(self, timer_id: str) -> dict[str, Any]:
        if not isinstance(timer_id, str) or not timer_id.strip():
            return {"success": False, "error": "Specify a timer ID to cancel."}

        with self._lock:
            entry = self._timers.pop(timer_id.strip(), None)
        if entry is None:
            return {"success": False, "error": "No active timer has that ID."}

        entry.timer.cancel()
        return {"success": True, "timer_id": entry.timer_id, "cancelled": True}

    def close(self) -> None:
        with self._lock:
            self._closed = True
            entries = list(self._timers.values())
            self._timers.clear()
        for entry in entries:
            entry.timer.cancel()

    def _notify_expiry(self, timer_id: str) -> None:
        with self._lock:
            entry = self._timers.pop(timer_id, None)
        if entry is None:
            return

        try:
            subprocess.run(
                [
                    "notify-send",
                    "--app-name=Jarvis",
                    "--expire-time=10000",
                    "Jarvis timer",
                    escape(entry.label, quote=False),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            print(f"[Timer notification error] {exc}")
