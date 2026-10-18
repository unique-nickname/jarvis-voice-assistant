import shutil
import subprocess

# Friendly names mapped to executable commands.
# Add or remove entries to match your installed applications.
ALLOWED_APPLICATIONS = {
    "zen": "zen-browser",
    "zen browser": "zen-browser",
    "browser": "zen-browser",
    "terminal": "kitty",
    "file manager": "thunar",
    "steam": "steam",
    "discord": "vesktop",
    "code editor": "code",
}


def control_volume(
    action: str,
    amount: int | None = None,
) -> dict:
    """Adjust, set, mute, or unmute the default audio output."""

    if action in ("up", "down"):
        if amount is None:
            amount = 5

        if not 1 <= amount <= 150:
            return {
                "success": False,
                "error": "Volume adjustment must be between 1 and 150 percent.",
            }

        change = f"{amount}%{'+' if action == 'up' else '-'}"
        command = [
            "wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", change
        ]

    elif action == "set":
        if amount is None or not 0 <= amount <= 150:
            return {
                "success": False,
                "error": "Target volume must be between 0 and 150 percent.",
            }

        command = [
            "wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@",
            f"{amount}%",
        ]

    elif action == "mute":
        command = [
            "wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"
        ]

    elif action == "unmute":
        command = [
            "wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"
        ]

    else:
        return {"success": False, "error": "Unsupported volume action."}

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )

        result = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )

        return {
            "success": True,
            "action": action,
            "status": result.stdout.strip(),
        }

    except (subprocess.SubprocessError, OSError) as exc:
        return {"success": False, "error": str(exc)}


def control_app_volume(
    app: str,
    action: str,
    amount: int | None = None,
    media: str | None = None,
) -> dict:
    """Control volume for an application or a matching media stream."""
    import json
    import subprocess

    action = action.strip().casefold()
    target = app.strip().casefold()
    media_target = media.strip().casefold() if media else None

    aliases = {
        "discord": {"vesktop", "discord"},
        "browser": {"zen", "zen-bin"},
        "zen browser": {"zen", "zen-bin"},
        "zen": {"zen", "zen-bin"},
    }
    app_names = aliases.get(target, {target})

    if action not in ("up", "down", "set", "mute", "unmute"):
        return {"success": False, "error": "Unsupported volume action."}

    if action in ("up", "down", "set"):
        if amount is None:
            return {"success": False, "error": "Specify a volume percentage."}

        if action in ("up", "down") and not 1 <= amount <= 150:
            return {"success": False, "error": "Adjustment must be 1–150 percent."}

        if action == "set" and not 0 <= amount <= 150:
            return {"success": False, "error": "Target volume must be 0–150 percent."}

    try:
        result = subprocess.run(
            ["pactl", "-f", "json", "list", "sink-inputs"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        streams = json.loads(result.stdout)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
        return {"success": False, "error": f"Could not list audio streams: {exc}"}

    app_streams = []

    for stream in streams:
        props = stream.get("properties") or {}

        names = {
            str(props.get("application.name") or "").casefold(),
            str(props.get("application.process.binary") or "").casefold(),
            str(props.get("node.name") or "").casefold(),
        }

        if names.intersection(app_names):
            app_streams.append(stream)

    if not app_streams:
        return {
            "success": False,
            "error": f"No audio streams currently found for '{app}'.",
        }

    matches = app_streams

    if media_target:
        matches = [
            stream
            for stream in app_streams
            if media_target in str(
                (stream.get("properties") or {}).get("media.name") or ""
            ).casefold()
        ]

        if not matches:
            available_media = [
                (stream.get("properties") or {}).get("media.name") or "(unknown)"
                for stream in app_streams
            ]
            return {
                "success": False,
                "error": (
                    f"No stream for '{app}' matched media '{media}'. "
                    f"Available media titles: {available_media}. "
                    "Media titles may be missing or unreliable."
                ),
            }

        if len(matches) > 1:
            return {
                "success": False,
                "error": (
                    f"Multiple streams matched '{media}'. "
                    "Refusing to change volume to avoid affecting the wrong stream."
                ),
            }

    changed = []

    for stream in matches:
        stream_id = str(stream["index"])
        props = stream.get("properties") or {}

        if action == "up":
            command = [
                "pactl", "set-sink-input-volume", stream_id, f"+{amount}%"
            ]
        elif action == "down":
            command = [
                "pactl", "set-sink-input-volume", stream_id, f"-{amount}%"
            ]
        elif action == "set":
            command = [
                "pactl", "set-sink-input-volume", stream_id, f"{amount}%"
            ]
        else:
            muted = "1" if action == "mute" else "0"
            command = [
                "pactl", "set-sink-input-mute", stream_id, muted
            ]

        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            changed.append({
                "stream_id": int(stream_id),
                "media": props.get("media.name") or "(unknown)",
            })
        except (subprocess.SubprocessError, OSError) as exc:
            return {
                "success": False,
                "error": f"Failed to change stream {stream_id}: {exc}",
                "changed_streams": changed,
            }

    return {
        "success": True,
        "app": app,
        "action": action,
        "streams_changed": len(changed),
        "streams": changed,
    }


def open_application(name: str) -> dict:
    """Launch an approved desktop application."""
    name = name.strip().lower()

    executable = ALLOWED_APPLICATIONS.get(name)
    if executable is None:
        return {
            "success": False,
            "message": (
                f"'{name}' is not an approved application. "
                f"Available applications: "
                f"{', '.join(ALLOWED_APPLICATIONS)}"
            ),
        }

    # Resolve the executable without invoking a shell.
    path = shutil.which(executable)
    if path is None:
        return {
            "success": False,
            "message": (
                f"'{executable}' was not found in PATH. "
                "Check whether the application is installed."
            ),
        }

    try:
        subprocess.Popen(
            [path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        return {
            "success": True,
            "message": f"Launched {name}.",
        }

    except OSError as exc:
        return {
            "success": False,
            "message": f"Could not launch {name}: {exc}",
        }

def get_system_status() -> dict:
    """Return current CPU, memory, and battery status."""
    import psutil

    # A short interval gives CPU usage a meaningful measurement.
    cpu_percent = psutil.cpu_percent(interval=0.5)

    memory = psutil.virtual_memory()

    status = {
        "cpu_usage_percent": cpu_percent,
        "memory_usage_percent": memory.percent,
        "memory_used_gb": round(memory.used / (1024 ** 3), 2),
        "memory_total_gb": round(memory.total / (1024 ** 3), 2),
    }

    battery = psutil.sensors_battery()

    if battery is not None:
        status["battery_percent"] = battery.percent
        status["plugged_in"] = battery.power_plugged
    else:
        status["battery_percent"] = None
        status["plugged_in"] = None

    return status