
from datetime import datetime
from tools.desktop import (
    open_application,
    get_system_status,
    control_volume,
    control_app_volume,
    control_media,
    control_clips,
)


TOOLS = [
    {
        "type": "function",
        "name": "get_local_time",
        "description": "Get the current local time and timezone.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "open_application",
        "description": (
            "Open an approved desktop application by its friendly name. "
            "Only applications in the allowlist are supported."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Friendly application name, such as "
                        "'firefox', 'terminal', or 'steam'."
                    ),
                }
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_system_status",
        "description": (
            "Get current CPU usage, RAM usage, and battery status "
            "when available. Use this when the user asks about "
            "system resource usage or battery level."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "control_volume",
        "description": (
            "Control the default audio output volume. "
            "Increase or decrease volume by a specified percentage, "
            "set it to an exact percentage, mute, or unmute."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["up", "down", "set", "mute", "unmute"],
                    "description": "The volume operation to perform.",
                },
                "amount": {
                    "type": ["integer", "null"],
                    "description": (
                        "Percentage to adjust by for up/down, or target "
                        "volume for set. Null for mute/unmute. "
                        "Omit only when the schema permits it."
                    ),
                },
            },
            "required": ["action", "amount"],
            "additionalProperties": False,
            "strict": True,
        },
    },
    {
        "type": "function",
        "name": "control_app_volume",
        "description": (
            "Adjust, set, mute, or unmute a specific application's audio. "
            "Use the application's exact name, such as Zen or vesktop."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Exact application name, such as Zen or vesktop.",
                },
                "action": {
                    "type": "string",
                    "enum": ["up", "down", "set", "mute", "unmute"],
                },
                "amount": {
                    "type": ["integer", "null"],
                    "description": "Percentage adjustment or target volume; null for mute/unmute.",
                },
            },
            "required": ["app", "action", "amount"],
            "additionalProperties": False,
            "strict": True,
        },
    },
    {
        "type": "function",
        "name": "control_media",
        "description": (
            "Control media playback through MPRIS. Use for commands like "
            "play, pause, resume, toggle playback, skip tracks, seek, "
            "check playback status, or identify the currently playing song. "
            "Works with supported media players and browser media sessions. "
            "Use now_playing to retrieve the title, artist, album, and URL. "
            "If the user names a specific player, pass its exact player ID. "
            "Otherwise, leave player null to select an active player. "
            "Seeking defaults to 10 seconds."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "play",
                        "pause",
                        "play_pause",
                        "next",
                        "previous",
                        "status",
                        "now_playing",
                        "seek_forward",
                        "seek_backward",
                    ],
                    "description": "The media operation to perform.",
                },
                "player": {
                    "type": ["string", "null"],
                    "description": (
                        "Exact player ID from playerctl --list-all, "
                        "or null for automatic selection."
                    ),
                },
                "seek_seconds": {
                    "type": "integer",
                    "description": (
                        "Seconds to seek forward or backward, from 1 to 300. "
                        "Use 10 for other actions."
                    ),
                },
            },
            "required": ["action", "player", "seek_seconds"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "control_clips",
        "description": (
            "Manage the GPU Screen Recorder replay buffer. "
            "Use action 'save' when the user asks to clip, save, "
            "or capture the last moments of gameplay or desktop activity. "
            "Use action 'status' to check whether the recorder is running. "
            "Saving sends a request to the running recorder; it does not "
            "start the recorder or guarantee the clip has finished writing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["save", "status"],
                    "description": "Save the current replay buffer or check recorder status.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def get_local_time():
    now = datetime.now().astimezone()
    return {
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "timezone": str(now.tzinfo),
    }


TOOL_HANDLERS = {
    "get_local_time": get_local_time,
    "open_application": open_application,
    "get_system_status": get_system_status,
    "control_volume": control_volume,
    "control_app_volume": control_app_volume,
    "control_media": control_media,
    "control_clips": control_clips,
}
