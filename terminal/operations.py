"""Construct the optional process-local terminal command service."""

from __future__ import annotations

import os
from pathlib import Path

from terminal.command_policy import tier_overrides_from_environment
from terminal.command_service import CommandTerminalService


def create_terminal_service(
    *,
    access_root: str | None = None,
    protected_paths: tuple[str | Path, ...] = (),
) -> CommandTerminalService | None:
    """Create the terminal service only when local configuration enables it."""
    enabled = os.environ.get("TERMINAL_COMMANDS_ENABLED", "false")
    if enabled.strip().casefold() not in {"1", "true", "yes", "on"}:
        return None
    if access_root is None:
        access_root = os.environ.get("TERMINAL_WRITE_ROOT", "~/")
    return CommandTerminalService(
        access_root,
        tier_overrides=tier_overrides_from_environment(),
        protected_paths=protected_paths,
    )
