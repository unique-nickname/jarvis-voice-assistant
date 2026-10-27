"""Narrow Hyprland window listing and focus operations."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any


_WINDOW_ID = re.compile(r"0x[0-9a-fA-F]+\Z")
_MAX_WINDOWS = 100


def _read_windows() -> tuple[list[dict[str, Any]] | None, str | None]:
    executable = shutil.which("hyprctl")
    if executable is None:
        return None, "Window tools require the Hyprland hyprctl executable."

    try:
        result = subprocess.run(
            [executable, "-j", "clients"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if len(result.stdout) > 2_000_000:
            return None, "Hyprland returned an oversized window list."
        clients = json.loads(result.stdout)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
        return None, f"Could not read Hyprland windows: {exc}"

    if not isinstance(clients, list):
        return None, "Hyprland returned an invalid window list."

    windows = []
    for client in clients:
        if not isinstance(client, dict):
            continue
        if client.get("mapped") is False:
            continue

        address = client.get("address")
        if not isinstance(address, str) or not _WINDOW_ID.fullmatch(address):
            continue

        workspace = client.get("workspace")
        workspace_name = None
        if isinstance(workspace, dict):
            workspace_name = workspace.get("name")

        focus_rank = client.get("focusHistoryID")
        windows.append({
            "window_id": address,
            "application": str(
                client.get("class") or client.get("initialClass") or "Unknown"
            )[:160],
            "title": str(client.get("title") or "")[:240],
            "workspace": workspace_name,
            "focused": focus_rank == 0,
        })

    return windows, None


def list_open_windows() -> dict[str, Any]:
    """List up to 100 mapped windows on the current Hyprland session."""
    windows, error = _read_windows()
    if error:
        return {"success": False, "error": error}

    return {
        "success": True,
        "windows": windows[:_MAX_WINDOWS],
        "truncated": len(windows) > _MAX_WINDOWS,
    }


def focus_window(match: str) -> dict[str, Any]:
    """Focus one uniquely matching live window by application or title."""
    if not isinstance(match, str) or not match.strip() or len(match) > 200:
        return {"success": False, "error": "Provide a window name to focus."}

    query = match.strip().casefold()
    windows, error = _read_windows()
    if error:
        return {"success": False, "error": error}

    exact = [
        window for window in windows
        if query in {
            window["application"].casefold(),
            window["title"].casefold(),
        }
    ]
    matches = exact or [
        window for window in windows
        if query in window["application"].casefold()
        or query in window["title"].casefold()
    ]

    if not matches:
        return {"success": False, "error": f"No window matched '{match}'."}
    if len(matches) > 1:
        return {
            "success": False,
            "error": "More than one window matched; specify a more exact name.",
            "matches": [
                {
                    "application": window["application"],
                    "title": window["title"],
                }
                for window in matches[:10]
            ],
        }

    window = matches[0]
    executable = shutil.which("hyprctl")
    if executable is None:
        return {"success": False, "error": "hyprctl is unavailable."}

    try:
        subprocess.run(
            [executable, "dispatch", "focuswindow", f"address:{window['window_id']}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return {"success": False, "error": f"Could not focus the window: {exc}"}

    return {
        "success": True,
        "application": window["application"],
        "title": window["title"],
    }
