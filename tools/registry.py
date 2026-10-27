
from datetime import datetime
from tools.desktop import (
    open_application,
    get_system_status,
    control_volume,
    control_app_volume,
    control_media,
    control_clips,
)
from tools.audio_outputs import list_audio_outputs, set_audio_output
from tools.file_actions import open_file, search_files
from tools.memory import MEMORY_TOOLS, create_memory_handlers
from tools.windows import focus_window, list_open_windows


TERMINAL_TOOLS = [
    {
        "type": "function",
        "name": "run_terminal_command",
        "description": (
            "Run one Fish command generated specifically for the user's request "
            "inside the configured filesystem sandbox. The application assigns "
            "the risk tier. Recognized read-only commands run "
            "without a prompt; modifying or unrecognized commands require "
            "approval in the local window by default. Known high-risk commands "
            "are denied by default; local tier overrides can change this routing. "
            "Inside the sandbox, HOME and ~ resolve to the configured terminal "
            "root, which may differ from the host home directory. This tool "
            "never elevates privileges."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The exact Fish command to run.",
                },
                "working_directory": {
                    "type": ["string", "null"],
                    "description": (
                        "Directory under the configured terminal root, or null "
                        "to use the root directory."
                    ),
                },
                "network_access": {
                    "type": "boolean",
                    "description": (
                        "Request network access. Set false unless the command "
                        "needs it. It cannot bypass Tier 2 approval; a mapping to "
                        "Tier 3 denies it."
                    ),
                },
            },
            "required": ["command", "working_directory", "network_access"],
            "additionalProperties": False,
        },
        "strict": True,
    }
]


TIMER_TOOLS = [
    {
        "type": "function",
        "name": "create_timer",
        "description": (
            "Create a one-shot desktop reminder while Jarvis is running. "
            "Use the user's requested duration and a short label."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "duration_seconds": {
                    "type": "integer",
                    "description": "Timer duration from 1 second to 86400 seconds.",
                },
                "label": {
                    "type": "string",
                    "description": "Short notification text describing the reminder.",
                },
            },
            "required": ["duration_seconds", "label"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "list_timers",
        "description": "List active one-shot timers and their remaining time.",
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
        "name": "cancel_timer",
        "description": "Cancel one active timer by the timer ID returned when it was created.",
        "parameters": {
            "type": "object",
            "properties": {
                "timer_id": {
                    "type": "string",
                    "description": "Exact active timer ID.",
                },
            },
            "required": ["timer_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


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
                        "'browser', 'terminal', or 'steam'."
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
            "Get current CPU, RAM, disk, operating-system, hostname, and "
            "battery status when available. Use this for questions about "
            "local system health or machine details."
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
        "name": "list_open_windows",
        "description": (
            "List visible windows on a Hyprland desktop, including app and "
            "title. Use this before focusing a window when the target is not "
            "uniquely known."
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
        "name": "focus_window",
        "description": (
            "Focus one existing Hyprland window by its app name or title. "
            "If several windows match, the tool refuses and returns candidates."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "match": {
                    "type": "string",
                    "description": "App name or window title to match.",
                },
            },
            "required": ["match"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "search_files",
        "description": (
            "Search filenames under the user's home directory. This searches "
            "names only, never file contents. Hidden folders are skipped, "
            "search is bounded, and paths outside home are refused."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name_query": {
                    "type": "string",
                    "description": "Filename fragment to search for.",
                },
                "directory": {
                    "type": ["string", "null"],
                    "description": "Optional starting directory under home, or null for home.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matches, from 1 to 20.",
                },
            },
            "required": ["name_query", "directory", "limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "open_file",
        "description": (
            "Open a user-selected supported document or media file under the "
            "home directory in its desktop application. It does not read the "
            "file contents. Use only when the user asks to open a file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The exact path returned by search_files or provided by the user.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "list_audio_outputs",
        "description": "List available audio output devices and identify the default.",
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
        "name": "set_audio_output",
        "description": (
            "Set the default audio output to one uniquely matching device. "
            "If a spoken name is ambiguous, list outputs and ask the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "match": {
                    "type": "string",
                    "description": "Exact or unique substring of the output name or description.",
                },
            },
            "required": ["match"],
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
                "media": {
                    "type": ["string", "null"],
                    "description": (
                        "Media title to select one stream; set to null to "
                        "target all streams for the app. Multiple title "
                        "matches are refused."
                    ),
                },
            },
            "required": ["app", "action", "amount", "media"],
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
            "Pass 10 for actions that do not seek; seek actions should specify "
            "the desired number of seconds."
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
    "list_open_windows": list_open_windows,
    "focus_window": focus_window,
    "search_files": search_files,
    "open_file": open_file,
    "list_audio_outputs": list_audio_outputs,
    "set_audio_output": set_audio_output,
}


def tools_for(memory_service=None, terminal_service=None, timer_service=None):
    """Return the tool schemas available to an assistant request."""
    available_tools = TOOLS
    if memory_service is not None:
        available_tools = [*available_tools, *MEMORY_TOOLS]
    if terminal_service is not None:
        available_tools = [*available_tools, *TERMINAL_TOOLS]
    if timer_service is not None:
        available_tools = [*available_tools, *TIMER_TOOLS]
    return available_tools


def handlers_for(memory_service=None, terminal_service=None, timer_service=None):
    """Return static handlers plus those bound to active services."""
    handlers = dict(TOOL_HANDLERS)
    if memory_service is not None:
        handlers.update(create_memory_handlers(memory_service))
    if terminal_service is not None:

        def run_terminal_command(command, working_directory, network_access):
            return terminal_service.run_command(
                command,
                working_directory,
                network_access,
            )

        handlers["run_terminal_command"] = run_terminal_command
    if timer_service is not None:
        handlers.update({
            "create_timer": timer_service.create_timer,
            "list_timers": timer_service.list_timers,
            "cancel_timer": timer_service.cancel_timer,
        })
    return handlers
