import shutil
import subprocess
import os
import signal

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


def control_media(
    action: str,
    player: str | None = None,
    seek_seconds: int = 10,
) -> dict:
    """Control media playback through MPRIS using playerctl."""
    import subprocess

    action = action.strip().casefold()
    valid_actions = {
        "play", "pause", "play_pause", "next", "previous",
        "status", "now_playing", "seek_forward", "seek_backward",
    }

    if action not in valid_actions:
        return {
            "success": False,
            "error": f"Unsupported media action: {action}",
        }

    if not 1 <= seek_seconds <= 300:
        return {
            "success": False,
            "error": "seek_seconds must be between 1 and 300.",
        }

    def run_playerctl(args: list[str]) -> str:
        result = subprocess.run(
            ["playerctl", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()

    try:
        players = run_playerctl(["--list-all"]).splitlines()
        players = [p.strip() for p in players if p.strip()]

        if player:
            if player not in players:
                return {
                    "success": False,
                    "error": (
                        f"Player '{player}' not found. "
                        f"Available players: {players}"
                    ),
                }
            selected = player
        else:
            # Prefer a player that is currently playing.
            selected = None
            for candidate in players:
                try:
                    status = run_playerctl([
                        "--player", candidate, "status"
                    ])
                    if status.casefold() == "playing":
                        selected = candidate
                        break
                except subprocess.SubprocessError:
                    continue

            # If nothing is playing, use the only available player.
            if selected is None and len(players) == 1:
                selected = players[0]

            if selected is None:
                return {
                    "success": False,
                    "error": (
                        "No uniquely identifiable active media player. "
                        f"Available players: {players}. "
                        "Specify a player to control paused sessions."
                    ),
                }

        prefix = ["--player", selected]

        if action == "status":
            status = run_playerctl([*prefix, "status"])
            return {
                "success": True,
                "player": selected,
                "status": status,
            }

        if action == "now_playing":
            metadata = {}
            for field in ("title", "artist", "album"):
                try:
                    metadata[field] = run_playerctl([
                        *prefix, "metadata", f"xesam:{field}"
                    ]) or None
                except subprocess.SubprocessError:
                    metadata[field] = None

            try:
                metadata["url"] = run_playerctl([
                    *prefix, "metadata", "xesam:url"
                ]) or None
            except subprocess.SubprocessError:
                metadata["url"] = None

            return {
                "success": True,
                "player": selected,
                **metadata,
            }

        if action in ("seek_forward", "seek_backward"):
            position = float(run_playerctl([
                *prefix, "position"
            ]))
            offset = seek_seconds if action == "seek_forward" else -seek_seconds
            new_position = max(0, position + offset)
            run_playerctl([
                *prefix, "position", str(new_position)
            ])
        else:
            command = {
                "play": "play",
                "pause": "pause",
                "play_pause": "play-pause",
                "next": "next",
                "previous": "previous",
            }[action]
            run_playerctl([*prefix, command])

        return {
            "success": True,
            "player": selected,
            "action": action,
        }

    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        return {
            "success": False,
            "error": f"Media control failed: {exc}",
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


def control_clips(action: str) -> dict:
    """Check GPU Screen Recorder or save the current replay buffer."""

    from voice.clip_recorder import get_active_recorder

    action = action.strip().casefold()

    if action not in ("save", "status"):
        return {
            "success": False,
            "error": "Unsupported clip action. Use 'save' or 'status'.",
        }

    if not shutil.which("gpu-screen-recorder"):
        return {
            "success": False,
            "error": (
                "GPU Screen Recorder is not installed or is not in PATH."
            ),
        }

    recorder = get_active_recorder()

    if recorder is not None:
        if action == "status":
            running = recorder.is_running()
            return {
                "success": True,
                "running": running,
                "message": (
                    "GPU Screen Recorder is running."
                    if running
                    else "GPU Screen Recorder is not running."
                ),
            }

        return recorder.save()

    # Find recorder processes by their actual executable path.
    # This avoids accidentally matching a shell command or another process.
    recorder_pids = []

    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue

            try:
                with open(f"/proc/{entry}/cmdline", "rb") as process_file:
                    argv = process_file.read().split(b"\0")

                if argv and argv[0]:
                    executable = os.path.basename(
                        os.fsdecode(argv[0])
                    )

                    if executable == "gpu-screen-recorder":
                        recorder_pids.append(int(entry))

            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue

    except OSError as exc:
        return {
            "success": False,
            "error": f"Could not inspect running processes: {exc}",
        }

    if not recorder_pids:
        return {
            "success": False,
            "action": action,
            "error": (
                "GPU Screen Recorder is not running. "
                "Start the replay buffer before saving a clip."
            ),
        }

    if len(recorder_pids) > 1:
        return {
            "success": False,
            "error": (
                "Multiple GPU Screen Recorder processes are running. "
                "Refusing to signal an ambiguous recorder."
            ),
        }

    if action == "status":
        return {
            "success": True,
            "running": True,
            "message": "GPU Screen Recorder is running.",
        }

    try:
        os.kill(recorder_pids[0], signal.SIGUSR1)

        return {
            "success": True,
            "action": "save",
            "message": (
                "Requested a replay-buffer save. "
                "The recorder may take a moment to finish writing the clip."
            ),
        }

    except (ProcessLookupError, PermissionError, OSError) as exc:
        return {
            "success": False,
            "error": f"Could not signal GPU Screen Recorder: {exc}",
        }
