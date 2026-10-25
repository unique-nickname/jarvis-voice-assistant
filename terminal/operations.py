"""Small, explicitly registered terminal operations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from terminal.policy import (
    ChangePreview,
    OperationDefinition,
    OperationRegistry,
    RiskTier,
    TerminalPolicyError,
)
from terminal.sandbox import BubblewrapExecutor, SandboxError
from terminal.service import OperationHandler, TerminalService


_KERNEL_INFO = re.compile(r"Linux [A-Za-z0-9_.+-]{1,96}\Z")


def _validate_kernel_info_arguments(arguments: Mapping[str, Any]) -> None:
    if arguments:
        raise TerminalPolicyError("Kernel information takes no arguments.")


def _preview_kernel_info(arguments: Mapping[str, Any]) -> ChangePreview:
    return ChangePreview(
        title="Read kernel information",
        description="Read the operating system name and kernel release.",
        affected_resources=("Operating system metadata",),
    )


def kernel_info_operation(
    executor: BubblewrapExecutor,
) -> tuple[OperationDefinition, OperationHandler]:
    """Return one fixed Tier 1 diagnostic and its sandboxed handler."""

    def handler(arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        _validate_kernel_info_arguments(arguments)
        result = executor.run("/usr/bin/uname", ("-sr",))
        if result.returncode != 0:
            raise SandboxError("Kernel diagnostic failed inside the sandbox.")
        kernel = result.stdout.strip()
        if not _KERNEL_INFO.fullmatch(kernel):
            raise SandboxError("Kernel diagnostic returned unexpected output.")
        return {"kernel": kernel}

    definition = OperationDefinition(
        operation_id="system.kernel_info",
        risk_tier=RiskTier.READ_ONLY,
        validate_arguments=_validate_kernel_info_arguments,
        build_preview=_preview_kernel_info,
    )
    return definition, handler


def create_terminal_service() -> TerminalService:
    """Create the process-local service with only the fixed kernel diagnostic."""
    definition, handler = kernel_info_operation(BubblewrapExecutor())
    operations = OperationRegistry((definition,))
    return TerminalService(operations, {definition.operation_id: handler})
