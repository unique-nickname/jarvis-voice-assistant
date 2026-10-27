"""Open Jarvis's local settings window on request."""

from __future__ import annotations

import os
import subprocess
import sys

from core.config import PROJECT_ROOT


_DISPLAY_VARIABLES = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP",
    "XDG_SESSION_DESKTOP",
    "HYPRLAND_INSTANCE_SIGNATURE",
    "DESKTOP_SESSION",
    "HOME",
    "XDG_CONFIG_HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "JARVIS_CONFIG_FILE",
)


def open_settings() -> dict[str, object]:
    """Launch the settings UI without passing Jarvis credentials to it."""
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return {
            "success": False,
            "error": "No graphical desktop display is available.",
        }
    try:
        import tkinter

        tkinter.TkVersion
    except ImportError:
        return {
            "success": False,
            "error": "Tkinter is unavailable in Jarvis's Python environment.",
        }
    environment = {
        name: os.environ[name]
        for name in _DISPLAY_VARIABLES
        if name in os.environ
    }
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "jarvis_ui.settings"],
            cwd=PROJECT_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
            shell=False,
        )
    except OSError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "process_id": process.pid}
