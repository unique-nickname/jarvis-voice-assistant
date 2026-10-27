"""In-process queue for delayed, explicitly requested Jarvis actions."""

from __future__ import annotations

import heapq
import html
import json
import math
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping


MAX_SCHEDULED_ACTIONS = 20
MAX_DELAY_SECONDS = 30 * 24 * 60 * 60
MAX_ARGUMENTS_JSON_CHARS = 4_096

DELAYABLE_TOOL_NAMES = frozenset({
    "open_application",
    "control_volume",
    "control_app_volume",
    "control_media",
    "control_clips",
    "focus_window",
    "open_file",
    "set_audio_output",
})

_DELAYABLE_TOOL_ACTIONS = {
    "control_media": frozenset({
        "play",
        "pause",
        "play_pause",
        "next",
        "previous",
        "seek_forward",
        "seek_backward",
    }),
    "control_clips": frozenset({"save"}),
}


SCHEDULED_TOOL_ACTION_TOOLS = [
    {
        "type": "function",
        "name": "queue_tool_action",
        "description": (
            "Queue one allowed purpose-built action to run after a delay. "
            "Use only for an explicit user request. tool_name must be one of "
            "the listed action tools, and arguments_json must be a JSON object "
            "containing exactly that tool's required arguments. For example, "
            "open_application takes {\"name\":\"zen browser\"}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "delay_seconds": {
                    "type": "integer",
                    "description": "Delay from 1 second to 30 days.",
                },
                "tool_name": {
                    "type": "string",
                    "enum": sorted(DELAYABLE_TOOL_NAMES),
                    "description": "The exact allowed purpose-built action tool name.",
                },
                "arguments_json": {
                    "type": "string",
                    "description": "JSON object with exactly the selected tool's arguments.",
                },
            },
            "required": ["delay_seconds", "tool_name", "arguments_json"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "list_scheduled_actions",
        "description": "List pending, running, and recent delayed actions.",
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
        "name": "cancel_scheduled_action",
        "description": "Cancel a pending delayed action by its returned action ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "string",
                    "description": "Exact ID returned when the action was queued.",
                },
            },
            "required": ["action_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]

SCHEDULED_TERMINAL_ACTION_TOOLS = [
    {
        "type": "function",
        "name": "queue_terminal_command",
        "description": (
            "Queue a Fish command generated specifically for the user's "
            "request. The application reclassifies it when due. Tier 2 still "
            "requires local approval at execution time; Tier 3 follows the "
            "configured terminal policy and is denied by default. Scheduling "
            "does not approve or execute the command."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "delay_seconds": {
                    "type": "integer",
                    "description": "Delay from 1 second to 30 days.",
                },
                "command": {
                    "type": "string",
                    "description": "Exact Fish command generated for this request.",
                },
                "working_directory": {
                    "type": ["string", "null"],
                    "description": "Directory under the configured terminal root, or null for its root.",
                },
                "network_access": {
                    "type": "boolean",
                    "description": "Whether the command needs network access.",
                },
            },
            "required": [
                "delay_seconds",
                "command",
                "working_directory",
                "network_access",
            ],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


@dataclass
class _ScheduledJob:
    action_id: str
    kind: str
    description: str
    due_at: str
    deadline: float
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"


class ScheduledActionService:
    """Run scheduled actions serially while one Jarvis process remains alive."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._jobs: dict[str, _ScheduledJob] = {}
        self._heap: list[tuple[float, int, str]] = []
        self._history: deque[dict[str, Any]] = deque(maxlen=20)
        self._tool_handlers: dict[str, Callable[..., Any]] = {}
        self._tool_schemas: dict[str, dict[str, Any]] = {}
        self._terminal_service: Any = None
        self._next_id = 1
        self._closed = False
        self._bound = False
        self._worker = threading.Thread(
            target=self._run,
            name="jarvis-scheduled-actions",
            daemon=True,
        )
        self._worker.start()

    def bind(
        self,
        tool_handlers: Mapping[str, Callable[..., Any]],
        tool_schemas: list[dict[str, Any]],
        terminal_service: Any = None,
    ) -> None:
        """Bind the current tool registry before exposing queue tools."""
        with self._condition:
            if self._bound:
                raise RuntimeError("Scheduled action service is already bound.")
            self._tool_handlers = {
                name: tool_handlers[name]
                for name in DELAYABLE_TOOL_NAMES
                if name in tool_handlers
            }
            self._tool_schemas = {
                schema["name"]: schema
                for schema in tool_schemas
                if schema.get("name") in DELAYABLE_TOOL_NAMES
            }
            self._terminal_service = terminal_service
            self._bound = True

    def queue_tool_action(
        self,
        delay_seconds: int,
        tool_name: str,
        arguments_json: str,
    ) -> dict[str, Any]:
        if not self._validate_delay(delay_seconds):
            return self._error("Delay must be between 1 second and 30 days.")
        if not isinstance(tool_name, str) or tool_name not in DELAYABLE_TOOL_NAMES:
            return self._error("That tool is not allowed in the delayed action queue.")
        if not isinstance(arguments_json, str) or len(arguments_json) > MAX_ARGUMENTS_JSON_CHARS:
            return self._error("Tool arguments must be a small JSON object.")

        try:
            arguments = json.loads(arguments_json)
        except (json.JSONDecodeError, RecursionError):
            return self._error("Tool arguments were not valid JSON.")
        if not isinstance(arguments, dict):
            return self._error("Tool arguments must be a JSON object.")

        validation_error = self._validate_tool_arguments(tool_name, arguments)
        if validation_error:
            return self._error(validation_error)
        if shutil.which("notify-send") is None:
            return self._error("Desktop notifications require notify-send.")

        handler = self._tool_handlers.get(tool_name)
        if handler is None:
            return self._error("The selected tool is not available in this session.")

        description = self._describe_tool_action(tool_name, arguments)
        return self._enqueue(
            delay_seconds=delay_seconds,
            kind="tool",
            description=description,
            payload={"tool_name": tool_name, "arguments": arguments},
        )

    def queue_terminal_command(
        self,
        delay_seconds: int,
        command: str,
        working_directory: str | None,
        network_access: bool,
    ) -> dict[str, Any]:
        if not self._validate_delay(delay_seconds):
            return self._error("Delay must be between 1 second and 30 days.")
        if self._terminal_service is None:
            return self._error("Terminal commands are disabled in this session.")
        if shutil.which("notify-send") is None:
            return self._error("Desktop notifications require notify-send.")

        preview = self._terminal_service.preview_command(
            command,
            working_directory,
            network_access,
        )
        if preview.get("status") != "ready":
            return {
                "success": False,
                "error": preview.get("detail", "The command cannot be scheduled."),
                "status": preview.get("status"),
                "source_tier": preview.get("source_tier"),
                "effective_tier": preview.get("effective_tier"),
            }

        result = self._enqueue(
            delay_seconds=delay_seconds,
            kind="terminal",
            description="Run a scheduled terminal command",
            payload={
                "command": command,
                "working_directory": preview["working_directory"],
                "network_access": network_access,
            },
            metadata={
                "source_tier": preview["source_tier"],
                "effective_tier": preview["effective_tier"],
            },
        )
        if result.get("success"):
            result["source_tier"] = preview["source_tier"]
            result["effective_tier"] = preview["effective_tier"]
            result["approval_required_at_execution"] = (
                preview["effective_tier"] == 2
            )
        return result

    def list_scheduled_actions(self) -> dict[str, Any]:
        with self._condition:
            current = [
                self._job_summary(job)
                for job in sorted(self._jobs.values(), key=lambda item: item.deadline)
            ]
            history = list(self._history)
        return {"success": True, "actions": current + history}

    def cancel_scheduled_action(self, action_id: str) -> dict[str, Any]:
        if not isinstance(action_id, str) or not action_id.strip():
            return self._error("Specify a scheduled action ID to cancel.")

        with self._condition:
            job = self._jobs.get(action_id.strip())
            if job is None:
                return self._error("No pending scheduled action has that ID.")
            if job.status != "pending":
                return self._error("That action is already running and cannot be cancelled.")

            self._jobs.pop(job.action_id)
            self._history.append({
                "action_id": job.action_id,
                "description": job.description,
                "status": "cancelled",
                "due_at": job.due_at,
            })
            self._condition.notify_all()

        return {
            "success": True,
            "action_id": job.action_id,
            "cancelled": True,
        }

    def close(self) -> None:
        """Cancel pending jobs; nothing queued is persisted across shutdown."""
        with self._condition:
            self._closed = True
            self._jobs.clear()
            self._heap.clear()
            self._condition.notify_all()
        self._worker.join(timeout=2)

    def _enqueue(
        self,
        *,
        delay_seconds: int,
        kind: str,
        description: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now().astimezone()
        due_at = (now + timedelta(seconds=delay_seconds)).isoformat(timespec="seconds")
        deadline = time.monotonic() + delay_seconds

        with self._condition:
            if self._closed:
                return self._error("Scheduled action service is shutting down.")
            active_count = sum(job.status in {"pending", "running"} for job in self._jobs.values())
            if active_count >= MAX_SCHEDULED_ACTIONS:
                return self._error(
                    f"At most {MAX_SCHEDULED_ACTIONS} scheduled actions can be active."
                )

            action_id = f"action-{self._next_id}"
            sequence = self._next_id
            self._next_id += 1
            job = _ScheduledJob(
                action_id=action_id,
                kind=kind,
                description=description,
                due_at=due_at,
                deadline=deadline,
                payload=payload,
                metadata=metadata or {},
            )
            self._jobs[action_id] = job
            heapq.heappush(self._heap, (deadline, sequence, action_id))
            self._condition.notify_all()

        return {
            "success": True,
            "action_id": action_id,
            "description": description,
            "due_at": due_at,
            "status": "pending",
        }

    def _run(self) -> None:
        while True:
            with self._condition:
                job = None
                while job is None:
                    if self._closed:
                        return

                    while self._heap:
                        _, _, action_id = self._heap[0]
                        queued_job = self._jobs.get(action_id)
                        if queued_job is None or queued_job.status != "pending":
                            heapq.heappop(self._heap)
                        else:
                            break

                    if not self._heap:
                        self._condition.wait()
                        continue

                    deadline, _, action_id = self._heap[0]
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        self._condition.wait(timeout=remaining)
                        continue

                    heapq.heappop(self._heap)
                    job = self._jobs.get(action_id)
                    if job is not None and job.status == "pending":
                        job.status = "running"
                    else:
                        job = None

            if job is not None:
                self._execute(job)

    def _execute(self, job: _ScheduledJob) -> None:
        if job.kind == "terminal" and job.metadata.get("effective_tier") == 2:
            self._notify(
                "Approval needed",
                "A scheduled Tier 2 command is due. Review the local approval window.",
            )

        try:
            if job.kind == "tool":
                tool_name = job.payload["tool_name"]
                handler = self._tool_handlers[tool_name]
                result = handler(**job.payload["arguments"])
                status = self._tool_result_status(result)
                summary = self._tool_result_summary(status, result)
            else:
                result = self._terminal_service.run_command(**job.payload)
                status = str(result.get("status", "failed"))
                summary = self._terminal_result_summary(status)
        except Exception as exc:
            status = "failed"
            summary = f"Scheduled action failed: {str(exc)[:160]}"

        completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        history_item = {
            "action_id": job.action_id,
            "description": job.description,
            "status": status,
            "due_at": job.due_at,
            "completed_at": completed_at,
            "summary": summary,
        }
        with self._condition:
            self._jobs.pop(job.action_id, None)
            self._history.append(history_item)
            self._condition.notify_all()

        self._notify("Scheduled action finished", summary)

    def _validate_tool_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str | None:
        schema = self._tool_schemas.get(tool_name)
        if schema is None or tool_name not in self._tool_handlers:
            return "The selected purpose-built tool is not available."

        parameters = schema.get("parameters", {})
        properties = parameters.get("properties", {})
        required = set(parameters.get("required", []))
        if set(arguments) != required:
            return "Tool arguments must contain exactly the tool's required fields."

        for name, value in arguments.items():
            property_schema = properties.get(name)
            if property_schema is None or not self._matches_type(
                value,
                property_schema.get("type"),
            ):
                return f"Tool argument '{name}' has the wrong type."
            choices = property_schema.get("enum")
            if choices is not None and value not in choices:
                return f"Tool argument '{name}' is not an allowed option."

        action = arguments.get("action")
        allowed_actions = _DELAYABLE_TOOL_ACTIONS.get(tool_name)
        if allowed_actions is not None and (
            not isinstance(action, str) or action not in allowed_actions
        ):
            return "That read-only action cannot be queued as a delayed action."

        if tool_name == "open_application":
            from tools.desktop import get_allowed_applications

            name = arguments.get("name")
            if (
                not isinstance(name, str)
                or name.strip().casefold() not in get_allowed_applications()
            ):
                return "Only allowlisted applications can be scheduled."

        return None

    @staticmethod
    def _matches_type(value: Any, expected: Any) -> bool:
        expected_types = expected if isinstance(expected, list) else [expected]
        for expected_type in expected_types:
            if expected_type == "null" and value is None:
                return True
            if expected_type == "string" and isinstance(value, str):
                return True
            if expected_type == "integer" and type(value) is int:
                return True
            if expected_type == "number" and type(value) in {int, float}:
                return math.isfinite(value)
            if expected_type == "boolean" and type(value) is bool:
                return True
            if expected_type == "object" and isinstance(value, dict):
                return True
            if expected_type == "array" and isinstance(value, list):
                return True
        return False

    @staticmethod
    def _validate_delay(delay_seconds: Any) -> bool:
        return (
            type(delay_seconds) is int
            and 1 <= delay_seconds <= MAX_DELAY_SECONDS
        )

    @staticmethod
    def _describe_tool_action(tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name == "open_application":
            return f"Open {str(arguments.get('name', 'application'))[:100]}"
        if tool_name == "focus_window":
            return f"Focus {str(arguments.get('match', 'window'))[:100]}"
        if tool_name == "open_file":
            return f"Open a file in the home folder"
        if tool_name == "set_audio_output":
            return f"Set audio output to {str(arguments.get('match', 'device'))[:100]}"
        if tool_name in {"control_volume", "control_app_volume"}:
            return "Change audio volume"
        if tool_name == "control_media":
            return f"Control media: {arguments.get('action', 'playback')}"
        if tool_name == "control_clips":
            return "Save the current replay clip"
        return "Run a purpose-built action"

    @staticmethod
    def _tool_result_status(result: Any) -> str:
        if isinstance(result, Mapping) and result.get("success") is True:
            return "completed"
        if isinstance(result, Mapping) and result.get("success") is False:
            return "failed"
        return "finished"

    @staticmethod
    def _tool_result_summary(status: str, result: Any) -> str:
        if status == "completed":
            return "Scheduled action completed."
        if status == "failed":
            detail = ""
            if isinstance(result, Mapping):
                detail = str(result.get("error") or result.get("message") or "")
            return f"Scheduled action failed. {detail[:140]}".strip()
        return "Scheduled action ran; its tool did not report a success status."

    @staticmethod
    def _terminal_result_summary(status: str) -> str:
        if status == "completed":
            return "Scheduled terminal command completed."
        if status == "denied":
            return "Scheduled terminal command was denied or not approved."
        return "Scheduled terminal command failed."

    @staticmethod
    def _job_summary(job: _ScheduledJob) -> dict[str, Any]:
        return {
            "action_id": job.action_id,
            "description": job.description,
            "status": job.status,
            "due_at": job.due_at,
            **job.metadata,
        }

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {"success": False, "error": message}

    @staticmethod
    def _notify(title: str, message: str) -> None:
        executable = shutil.which("notify-send")
        if executable is None:
            print(f"[Scheduled action notification unavailable] {message}")
            return
        try:
            subprocess.run(
                [
                    executable,
                    "--app-name=Jarvis",
                    "--expire-time=10000",
                    html.escape(title, quote=False),
                    html.escape(message[:240], quote=False),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            print(f"[Scheduled action notification error] {exc}")
