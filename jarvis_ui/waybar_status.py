"""Emit the current Jarvis state for a Waybar custom JSON module."""

from __future__ import annotations

import json
import sys

from core.status import read_runtime_status


STATE_LABELS = {
    "starting": "Starting",
    "wake_word": "Waiting for wake word",
    "listening_command": "Listening for a command",
    "thinking": "Thinking",
    "executing": "Executing a tool",
    "waiting_approval": "Waiting for approval",
    "speaking": "Speaking",
    "follow_up": "Waiting for follow-up",
    "error": "Attention needed",
    "stopped": "Stopped",
    "already_running": "Already running",
    "stopping": "Stopping",
}


def waybar_payload() -> dict[str, str]:
    state = read_runtime_status()
    return {
        "text": "●",
        "tooltip": f"Jarvis · {STATE_LABELS.get(state, 'Stopped')}",
        "class": state,
        "alt": state,
    }


def main() -> None:
    print(json.dumps(waybar_payload(), ensure_ascii=False), file=sys.stdout, flush=True)


if __name__ == "__main__":
    main()
