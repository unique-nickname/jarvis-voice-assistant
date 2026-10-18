
from datetime import datetime
from tools.desktop import open_application, get_system_status, control_volume, control_app_volume


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
}
