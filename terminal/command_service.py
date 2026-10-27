"""Tier routing and execution for the single assistant terminal command tool."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from terminal.approval_ui import review_approval
from terminal.command_policy import CommandAssessment, assess_command
from terminal.policy import (
    ChangePreview,
    OperationDefinition,
    OperationRegistry,
    RiskTier,
    TerminalPolicyError,
)
from terminal.sandbox import BubblewrapExecutor, SandboxError
from terminal.service import (
    ApprovalReviewer,
    ExecutionStatus,
    OperationExecution,
    OperationHandler,
    TerminalService,
)


_READ_OPERATION_ID = "terminal.command.read_only"
_APPROVED_OPERATION_ID = "terminal.command.approved"


class CommandTerminalService(TerminalService):
    """Classify assistant-generated commands and run them through tier policy."""

    def __init__(
        self,
        access_root: str | Path,
        *,
        executor: BubblewrapExecutor | None = None,
        reviewer: ApprovalReviewer = review_approval,
        tier_overrides: Mapping[RiskTier, RiskTier] | None = None,
        protected_paths: tuple[str | Path, ...] = (),
    ) -> None:
        try:
            self.access_root = Path(access_root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, TypeError) as exc:
            raise ValueError(
                "Terminal access root must be an existing directory."
            ) from exc
        if not self.access_root.is_dir() or self.access_root == Path("/"):
            raise ValueError("Terminal access root must be a non-root directory.")
        resolved_protected_paths = []
        for protected_path in protected_paths:
            try:
                protected = Path(protected_path).expanduser().resolve(strict=True)
            except FileNotFoundError:
                continue
            except (OSError, RuntimeError, TypeError) as exc:
                raise ValueError(
                    "A protected application path is unavailable."
                ) from exc
            if protected.is_dir() and self.access_root.is_relative_to(protected):
                raise ValueError(
                    "The terminal root cannot be inside protected application data."
                )
            resolved_protected_paths.append(protected)

        self.tier_overrides = MappingProxyType(
            self._validate_tier_overrides(tier_overrides)
        )
        self._executor = executor or BubblewrapExecutor(
            timeout_seconds=30,
            protected_paths=tuple(resolved_protected_paths),
        )
        self._command_lock = threading.Lock()

        read_definition = OperationDefinition(
            operation_id=_READ_OPERATION_ID,
            risk_tier=RiskTier.READ_ONLY,
            validate_arguments=self._validate_read_arguments,
            build_preview=self._build_read_preview,
        )
        approved_definition = OperationDefinition(
            operation_id=_APPROVED_OPERATION_ID,
            risk_tier=RiskTier.MODIFICATION,
            validate_arguments=self._validate_approved_arguments,
            build_preview=self._build_approved_preview,
        )
        definitions = (read_definition, approved_definition)
        handlers: dict[str, OperationHandler] = {
            _READ_OPERATION_ID: self._execute_read_only,
            _APPROVED_OPERATION_ID: self._execute_approved,
        }
        super().__init__(OperationRegistry(definitions), handlers, reviewer=reviewer)

    def run_command(
        self,
        command: str,
        working_directory: str | None = None,
        network_access: bool = False,
    ) -> dict[str, Any]:
        """Apply local tier policy, requesting approval for every Tier 2 plan."""
        with self._command_lock:
            return self._run_command_serialized(
                command,
                working_directory,
                network_access,
            )

    def _run_command_serialized(
        self,
        command: str,
        working_directory: str | None,
        network_access: bool,
    ) -> dict[str, Any]:
        try:
            assessment, source_tier, effective_tier, cwd = self._assess_request(
                command,
                working_directory,
                network_access,
            )
        except (TerminalPolicyError, SandboxError, ValueError) as exc:
            return {
                "operation_id": "terminal.command",
                "status": ExecutionStatus.FAILED.value,
                "detail": str(exc),
            }

        if effective_tier is RiskTier.HIGH_RISK:
            return {
                "operation_id": "terminal.command",
                "status": ExecutionStatus.DENIED.value,
                "detail": "tier_3_denied_by_default",
                "source_tier": int(source_tier),
                "effective_tier": int(effective_tier),
            }

        arguments = {
            "command": command,
            "working_directory": str(cwd),
            "network_access": network_access,
            "source_tier": int(source_tier),
            "effective_tier": int(effective_tier),
        }
        operation_id = (
            _READ_OPERATION_ID
            if effective_tier is RiskTier.READ_ONLY
            else _APPROVED_OPERATION_ID
        )
        execution = self.execute(operation_id, arguments)
        if (
            execution.status is ExecutionStatus.COMPLETED
            and execution.result is not None
            and execution.result.get("exit_code") != 0
        ):
            execution = OperationExecution(
                execution.operation_id,
                ExecutionStatus.FAILED,
                result=execution.result,
                detail="command_exit_nonzero",
            )
        return execution.as_dict()

    def preview_command(
        self,
        command: str,
        working_directory: str | None = None,
        network_access: bool = False,
    ) -> dict[str, Any]:
        """Classify and scope a command without executing or approving it."""
        try:
            _, source_tier, effective_tier, cwd = self._assess_request(
                command,
                working_directory,
                network_access,
            )
        except (TerminalPolicyError, SandboxError, ValueError) as exc:
            return {
                "status": ExecutionStatus.FAILED.value,
                "detail": str(exc),
            }

        if effective_tier is RiskTier.HIGH_RISK:
            return {
                "status": ExecutionStatus.DENIED.value,
                "detail": "tier_3_denied_by_default",
                "source_tier": int(source_tier),
                "effective_tier": int(effective_tier),
                "working_directory": str(cwd),
            }

        return {
            "status": "ready",
            "source_tier": int(source_tier),
            "effective_tier": int(effective_tier),
            "working_directory": str(cwd),
        }

    def _assess_request(
        self,
        command: str,
        working_directory: str | None,
        network_access: bool,
    ) -> tuple[CommandAssessment, RiskTier, RiskTier, Path]:
        assessment = assess_command(command)
        if type(network_access) is not bool:
            raise TerminalPolicyError("Network access must be true or false.")
        assessment = self._promote_network_request(assessment, network_access)
        source_tier = assessment.risk_tier
        effective_tier = self._effective_tier(source_tier, network_access)
        cwd = self._resolve_working_directory(working_directory)
        return assessment, source_tier, effective_tier, cwd

    def _resolve_working_directory(self, requested: str | None) -> Path:
        if requested is None or requested == "":
            candidate = self.access_root
        elif not isinstance(requested, str):
            raise TerminalPolicyError("Working directory must be text or null.")
        else:
            path = Path(requested).expanduser()
            candidate = path if path.is_absolute() else self.access_root / path
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise TerminalPolicyError("Working directory is unavailable.") from exc
        if not resolved.is_dir():
            raise TerminalPolicyError("Working directory must be a directory.")
        try:
            resolved.relative_to(self.access_root)
        except ValueError as exc:
            raise TerminalPolicyError(
                "Working directory is outside the allowed root."
            ) from exc
        return resolved

    def _validate_arguments(
        self,
        arguments: Mapping[str, Any],
        expected_tier: RiskTier,
    ) -> CommandAssessment:
        if set(arguments) != {
            "command",
            "working_directory",
            "network_access",
            "source_tier",
            "effective_tier",
        }:
            raise TerminalPolicyError("Command request fields are invalid.")
        if type(arguments["network_access"]) is not bool:
            raise TerminalPolicyError("Network access must be true or false.")
        assessment = assess_command(arguments["command"])
        assessment = self._promote_network_request(
            assessment,
            arguments["network_access"],
        )
        source_tier = assessment.risk_tier
        effective_tier = self._effective_tier(
            source_tier,
            arguments["network_access"],
        )
        if (
            type(arguments["source_tier"]) is not int
            or arguments["source_tier"] != int(source_tier)
        ):
            raise TerminalPolicyError("Command source tier changed during validation.")
        if (
            type(arguments["effective_tier"]) is not int
            or arguments["effective_tier"] != int(effective_tier)
        ):
            raise TerminalPolicyError("Command effective tier changed during validation.")
        if effective_tier is not expected_tier:
            raise TerminalPolicyError("Command tier changed during validation.")
        cwd = self._resolve_working_directory(arguments["working_directory"])
        if str(cwd) != arguments["working_directory"]:
            raise TerminalPolicyError("Working directory changed during validation.")
        return assessment

    def _validate_read_arguments(self, arguments: Mapping[str, Any]) -> None:
        self._validate_arguments(arguments, RiskTier.READ_ONLY)

    def _validate_approved_arguments(self, arguments: Mapping[str, Any]) -> None:
        self._validate_arguments(arguments, RiskTier.MODIFICATION)

    def _build_read_preview(self, arguments: Mapping[str, Any]) -> ChangePreview:
        return ChangePreview(
            title="Run command without approval",
            description=(
                "The configured tier mapping routes this command to Tier 1. "
                "The command runs in the sandbox with the configured terminal root."
            ),
            affected_resources=(
                f"Working directory: {arguments['working_directory']}",
                f"Configured terminal root: {self.access_root}",
                (
                    "Risk tier mapping: Tier "
                    f"{arguments['source_tier']} to Tier {arguments['effective_tier']}"
                ),
            ),
        )

    def _build_approved_preview(self, arguments: Mapping[str, Any]) -> ChangePreview:
        return ChangePreview(
            title="Review terminal command",
            description=(
                "Run the exact Fish command shown in the validated arguments. "
                "The sandbox can write only inside the configured terminal root. "
                "It runs as your normal user in a rootless namespace with no "
                "host-root privileges. Privilege elevation is unavailable. "
                f"Network access is {'enabled' if arguments['network_access'] else 'disabled'}."
            ),
            affected_resources=(
                f"Working directory: {arguments['working_directory']}",
                f"Writable root after approval: {self.access_root}",
                f"Network access: {'enabled' if arguments['network_access'] else 'disabled'}",
                (
                    "Risk tier mapping: Tier "
                    f"{arguments['source_tier']} to Tier {arguments['effective_tier']}"
                ),
            ),
        )

    def _execute_read_only(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        assessment = self._validate_arguments(arguments, RiskTier.READ_ONLY)
        if assessment.risk_tier is RiskTier.READ_ONLY and assessment.argv is not None:
            result = self._executor.run_read_only_argv(
                assessment.argv,
                access_root=self.access_root,
                working_directory=arguments["working_directory"],
            )
        else:
            result = self._executor.run_fish_command(
                arguments["command"],
                access_root=self.access_root,
                working_directory=arguments["working_directory"],
                writable=True,
                network_access=arguments["network_access"],
            )
        return self._result_payload(
            arguments,
            result.returncode,
            result.stdout,
            result.stderr,
        )

    def _execute_approved(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        self._validate_arguments(arguments, RiskTier.MODIFICATION)
        result = self._executor.run_fish_command(
            arguments["command"],
            access_root=self.access_root,
            working_directory=arguments["working_directory"],
            writable=True,
            network_access=arguments["network_access"],
        )
        return self._result_payload(
            arguments,
            result.returncode,
            result.stdout,
            result.stderr,
        )

    def _result_payload(
        self,
        arguments: Mapping[str, Any],
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> Mapping[str, Any]:
        return {
            "command": arguments["command"],
            "access_root": str(self.access_root),
            "sandbox_home": str(self.access_root),
            "working_directory": arguments["working_directory"],
            "source_tier": arguments["source_tier"],
            "effective_tier": arguments["effective_tier"],
            "exit_code": returncode,
            "stdout": stdout,
            "stderr": stderr,
        }

    @staticmethod
    def _promote_network_request(
        assessment: CommandAssessment,
        network_access: bool,
    ) -> CommandAssessment:
        if network_access and assessment.risk_tier is RiskTier.READ_ONLY:
            return CommandAssessment(
                RiskTier.MODIFICATION,
                "network_access_requires_approval",
            )
        return assessment

    def _effective_tier(
        self,
        source_tier: RiskTier,
        network_access: bool,
    ) -> RiskTier:
        effective_tier = self.tier_overrides[source_tier]
        if network_access and effective_tier is RiskTier.READ_ONLY:
            return RiskTier.MODIFICATION
        return effective_tier

    @staticmethod
    def _validate_tier_overrides(
        tier_overrides: Mapping[RiskTier, RiskTier] | None,
    ) -> dict[RiskTier, RiskTier]:
        overrides = {tier: tier for tier in RiskTier}
        if tier_overrides is None:
            return overrides
        if not isinstance(tier_overrides, Mapping):
            raise ValueError("Terminal tier overrides must be a mapping.")
        for source_tier, target_tier in tier_overrides.items():
            if not isinstance(source_tier, RiskTier) or not isinstance(
                target_tier, RiskTier
            ):
                raise ValueError("Terminal tier overrides must use tiers 1, 2, or 3.")
            overrides[source_tier] = target_tier
        return overrides
