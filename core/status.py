"""Small, opt-in status protocol for a supervising launcher."""

from __future__ import annotations

import os
import sys


def emit_runtime_status(state: str) -> None:
    """Write one machine-readable state line when a UI launcher requests it."""
    if not state.isascii() or not state.replace("_", "").isalnum():
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
        return
    if os.environ.get("JARVIS_STATUS_OUTPUT") == "1":
        print(message.decode("ascii"), end="", file=sys.stdout, flush=True)
