
from datetime import datetime
from tools.desktop import open_application, get_system_status


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
}
