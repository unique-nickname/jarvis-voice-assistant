"""Local Zenity approval dialog for Tier 2 plans.

This adapter only changes approval state. It never launches the operation in a
plan. If the dialog cannot be shown, the request remains unapproved.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import subprocess
import time
from pathlib import Path

from terminal.approval import ApprovalError, ApprovalQueue, ApprovalState
from terminal.policy import RiskTier


_ZENITY_PATHS = (Path("/usr/bin/zenity"), Path("/bin/zenity"))
_HYPRCTL_PATHS = (Path("/usr/bin/hyprctl"), Path("/bin/hyprctl"))
_APPROVAL_WINDOW_TITLE = "Jarvis: Review requested change"
_WINDOW_ADDRESS = re.compile(r"0x[0-9a-fA-F]+\Z")
_DISPLAY_ENVIRONMENT = (
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
    "XDG_DATA_HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
)
_LOGGER = logging.getLogger(__name__)


class ApprovalWindowError(RuntimeError):
    """Raised if the approval window cannot be displayed reliably."""


def _find_zenity() -> str:
    for candidate in _ZENITY_PATHS:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise ApprovalWindowError("Zenity is not installed in a supported system path.")


def _find_hyprctl() -> str | None:
    for candidate in _HYPRCTL_PATHS:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _should_float_window() -> bool:
    mode = os.environ.get("TERMINAL_APPROVAL_FLOATING", "auto").strip().casefold()
    if mode == "never":
        return False
    if mode == "always":
        return True
    if mode != "auto":
        mode = "auto"

    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return True
    desktop_names = {
        name.strip().casefold()
        for variable in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP")
        for name in os.environ.get(variable, "").split(":")
    }
    return "hyprland" in desktop_names


def _display_environment() -> dict[str, str]:
    return {
        name: os.environ[name]
        for name in _DISPLAY_ENVIRONMENT
        if name in os.environ
    }


def _find_window_address(
    hyprctl: str,
    process_id: int,
) -> str | None:
    try:
        result = subprocess.run(
            [hyprctl, "-j", "clients"],
            text=True,
            capture_output=True,
            check=False,
            close_fds=True,
            shell=False,
            env=_display_environment(),
            timeout=0.5,
        )
        if result.returncode != 0:
            return None
        clients = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None

    if not isinstance(clients, list):
        return None
    for client in clients:
        if not isinstance(client, dict):
            continue
        titles = (client.get("title"), client.get("initialTitle"))
        if (
            client.get("pid") != process_id
            or _APPROVAL_WINDOW_TITLE not in titles
        ):
            continue
        address = client.get("address")
        if isinstance(address, str) and _WINDOW_ADDRESS.fullmatch(address):
            return address
    return None


def _request_floating(hyprctl: str, address: str) -> bool:
    environment = _display_environment()
    selector = json.dumps(f"address:{address}")
    lua_dispatcher = (
        "hl.dsp.window.float({ action = \"on\", "
        f"window = {selector} }})"
    )
    lua_result = subprocess.run(
        [hyprctl, "dispatch", lua_dispatcher],
        text=True,
        capture_output=True,
        check=False,
        close_fds=True,
        shell=False,
        env=environment,
        timeout=1.5,
    )
    if lua_result.returncode == 0:
        return True

    legacy_result = subprocess.run(
        [hyprctl, "dispatch", "setfloating", f"address:{address}"],
        text=True,
        capture_output=True,
        check=False,
        close_fds=True,
        shell=False,
        env=environment,
        timeout=1.5,
    )
    if legacy_result.returncode == 0:
        return True

    legacy_detail = (legacy_result.stderr or legacy_result.stdout).strip()[:200]
    lua_detail = (lua_result.stderr or lua_result.stdout).strip()[:200]
    _LOGGER.warning(
        "Hyprland did not float the approval window (legacy exit %s: %s; "
        "Lua exit %s: %s).",
        legacy_result.returncode,
        legacy_detail or "no error detail",
        lua_result.returncode,
        lua_detail or "no error detail",
    )
    return False


def _float_zenity_window(process: subprocess.Popen[str]) -> None:
    hyprctl = _find_hyprctl()
    if hyprctl is None:
        return

    deadline = time.monotonic() + 3.0
    while process.poll() is None and time.monotonic() < deadline:
        address = _find_window_address(hyprctl, process.pid)
        if address is not None:
            try:
                _request_floating(hyprctl, address)
            except (OSError, subprocess.TimeoutExpired):
                _LOGGER.warning("Could not request floating for the approval window.")
            return
        time.sleep(0.1)
    _LOGGER.warning(
        "Could not identify the approval window in Hyprland (Zenity PID %s); "
        "leaving its layout unchanged.",
        process.pid,
    )


def _run_zenity(
    command: list[str],
    content: str,
    timeout_seconds: int,
    *,
    float_window: bool,
) -> subprocess.CompletedProcess[str]:
    environment = _display_environment()
    if not float_window:
        return subprocess.run(
            command,
            input=content,
            text=True,
            capture_output=True,
            check=False,
            close_fds=True,
            shell=False,
            env=environment,
            timeout=timeout_seconds + 2,
        )

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        close_fds=True,
        shell=False,
        env=environment,
    )
    if process.stdin is None:
        _stop_process(process)
        raise ApprovalWindowError("Could not provide the approval details to Zenity.")
    try:
        process.stdin.write(content)
        process.stdin.close()
    except OSError as exc:
        _stop_process(process)
        raise ApprovalWindowError("Could not provide the approval details to Zenity.") from exc

    _float_zenity_window(process)
    try:
        return_code = process.wait(timeout=timeout_seconds + 2)
    except subprocess.TimeoutExpired:
        _stop_process(process)
        return_code = 5
    return subprocess.CompletedProcess(command, return_code, "", "")


def _stop_process(process: subprocess.Popen[str]) -> None:
    try:
        if process.poll() is None:
            process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _format_ticket(ticket) -> str:
    plan = ticket.plan
    resources = "\n".join(
        f"  • {resource}" for resource in plan.preview.affected_resources
    ) or "  None listed"
    arguments = json.dumps(
        plan.arguments,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    return (
        "Review this requested change. Approve it only if the described effect "
        "is intended.\n\n"
        f"Risk tier: {int(plan.risk_tier)} (modification)\n"
        f"Operation: {plan.operation_id}\n"
        f"Change: {plan.preview.title}\n\n"
        f"Description:\n{plan.preview.description}\n\n"
        f"Affected resources:\n{resources}\n\n"
        f"Validated arguments (escaped JSON):\n{arguments}\n\n"
        f"This request expires in about {math.ceil(ticket.expires_in_seconds)} seconds."
    )


def review_approval(queue: ApprovalQueue, request_id: str) -> ApprovalState:
    """Show a local dialog for the canonical queued plan and record the choice.

    Zenity exit status 0 means Approve; Cancel, Deny, and timeout never approve.
    The parent verifies the request is still pending when recording the choice.
    """
    ticket = queue.pending_ticket(request_id)
    if ticket.plan.risk_tier is not RiskTier.MODIFICATION:
        raise ApprovalError("Only Tier 2 operations may use this approval window.")
    if not math.isfinite(ticket.expires_in_seconds) or ticket.expires_in_seconds <= 0:
        return queue.state(request_id)
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise ApprovalWindowError("No graphical desktop display is available.")

    timeout_seconds = max(1, math.ceil(ticket.expires_in_seconds))
    command = [
        _find_zenity(),
        "--text-info",
        f"--title={_APPROVAL_WINDOW_TITLE}",
        "--ok-label=Approve",
        "--cancel-label=Deny",
        "--default-cancel",
        "--modal",
        "--width=800",
        "--height=600",
        f"--timeout={timeout_seconds}",
    ]

    from core.status import emit_runtime_status

    emit_runtime_status("waiting_approval")
    try:
        result = _run_zenity(
            command,
            _format_ticket(ticket),
            timeout_seconds,
            float_window=_should_float_window(),
        )
    except subprocess.TimeoutExpired:
        return _deny_if_pending(queue, request_id)
    except OSError as exc:
        raise ApprovalWindowError("Could not start the local approval window.") from exc
    finally:
        emit_runtime_status("executing")

    if result.returncode == 0:
        return queue.approve_from_ui(request_id).state
    if result.returncode in (1, 5):
        return _deny_if_pending(queue, request_id)
    raise ApprovalWindowError("The approval window exited unexpectedly.")


def _deny_if_pending(queue: ApprovalQueue, request_id: str) -> ApprovalState:
    state = queue.state(request_id)
    if state is ApprovalState.PENDING:
        return queue.deny_from_ui(request_id).state
    return state
