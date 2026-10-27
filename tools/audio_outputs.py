"""List and select PulseAudio-compatible output devices."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


def _run_pactl(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("pactl")
    if executable is None:
        raise FileNotFoundError("pactl is unavailable.")
    return subprocess.run(
        [executable, *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )


def list_audio_outputs() -> dict[str, Any]:
    """List current output devices and identify the default device."""
    try:
        result = _run_pactl(["-f", "json", "list", "sinks"])
        sinks = json.loads(result.stdout)
        default_result = _run_pactl(["get-default-sink"])
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
        return {"success": False, "error": f"Could not list audio outputs: {exc}"}

    if not isinstance(sinks, list):
        return {
            "success": False,
            "error": "Audio service returned an invalid device list.",
        }

    default_name = default_result.stdout.strip()
    outputs = []
    for sink in sinks[:50]:
        if not isinstance(sink, dict) or not isinstance(sink.get("name"), str):
            continue
        outputs.append({
            "name": sink["name"][:200],
            "description": str(sink.get("description") or sink["name"])[:200],
            "is_default": sink["name"] == default_name,
            "state": str(sink.get("state") or "unknown")[:40],
        })

    return {
        "success": True,
        "outputs": outputs,
        "truncated": len(sinks) > 50,
    }


def set_audio_output(match: str) -> dict[str, Any]:
    """Set the default output only when one device matches unambiguously."""
    if not isinstance(match, str) or not match.strip() or len(match) > 200:
        return {"success": False, "error": "Specify an audio output name."}

    listing = list_audio_outputs()
    if not listing.get("success"):
        return listing

    query = match.strip().casefold()
    outputs = listing["outputs"]
    exact = [
        output for output in outputs
        if query in {output["name"].casefold(), output["description"].casefold()}
    ]
    matches = exact or [
        output for output in outputs
        if query in output["name"].casefold()
        or query in output["description"].casefold()
    ]

    if not matches:
        return {"success": False, "error": f"No audio output matched '{match}'."}
    if len(matches) > 1:
        return {
            "success": False,
            "error": "More than one audio output matched; specify a more exact name.",
            "matches": [
                {"name": output["name"], "description": output["description"]}
                for output in matches[:10]
            ],
        }

    selected = matches[0]
    try:
        _run_pactl(["set-default-sink", selected["name"]])
        current = _run_pactl(["get-default-sink"]).stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        return {"success": False, "error": f"Could not select audio output: {exc}"}

    if current != selected["name"]:
        return {
            "success": False,
            "error": "Audio service did not confirm the new default output.",
        }

    return {
        "success": True,
        "name": selected["name"],
        "description": selected["description"],
    }
