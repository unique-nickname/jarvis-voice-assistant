"""Route structured terminal plans through tier policy and approval.

This module invokes only trusted, application-registered Python handlers. It
does not accept command text or provide an operating-system sandbox.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from terminal.approval import ApprovalError, ApprovalQueue, ApprovalState
from terminal.approval_ui import review_approval
from terminal.policy import (
    OperationPlan,
    OperationRegistry,
    RiskTier,
    TerminalPolicyError,
)


MAX_RESULT_BYTES = 16_384

OperationHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]
ApprovalReviewer = Callable[[ApprovalQueue, str], ApprovalState]


class ExecutionStatus(str, Enum):
    COMPLETED = "completed"
    DENIED = "denied"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OperationExecution:
    """Bounded response returned by one trusted operation handler."""

    operation_id: str
    status: ExecutionStatus
    result: dict[str, Any] | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        response: dict[str, Any] = {
            "operation_id": self.operation_id,
            "status": self.status.value,
        }
        if self.result is not None:
            if any(not isinstance(key, str) for key in self.result):
                raise ValueError("Execution result keys must be strings.")
            serialized = json.dumps(
                self.result,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
            )
            if len(serialized.encode("utf-8")) > MAX_RESULT_BYTES:
                raise ValueError("Execution result exceeds the size limit.")
            response["result"] = json.loads(serialized)
        if self.detail is not None:
            response["detail"] = self.detail
        return response


class TerminalService:
    """Apply risk-tier routing before invoking a registered handler.

    Handlers are trusted code supplied by the application, never model input.
    Tier 1 handlers run directly. Tier 2 handlers run only after the local
    reviewer approves and the corresponding immutable plan is consumed once.
    Tier 3 operations have no execution path.

    This service does not isolate handler code from the host. It must not be
    used with handlers that access host resources or launch processes unless
    those effects run through a separate, verified OS sandbox.
    """

    def __init__(
        self,
        operations: OperationRegistry,
        handlers: Mapping[str, OperationHandler],
        *,
        reviewer: ApprovalReviewer = review_approval,
    ) -> None:
        if not callable(reviewer):
            raise TypeError("An approval reviewer is required.")
        self._operations = operations
        self._handlers = dict(handlers)
        for operation_id, handler in self._handlers.items():
            if not callable(handler):
                raise TypeError("Operation handlers must be callable.")
            self._operations.tier_for(operation_id)
        self._reviewer = reviewer
        self._approvals = ApprovalQueue(operations)

    def execute(
        self,
        operation_id: str,
        arguments: Mapping[str, Any],
    ) -> OperationExecution:
        """Validate, authorize, and invoke one registered operation."""
        risk_tier = self._operations.tier_for(operation_id)
        if risk_tier is RiskTier.HIGH_RISK:
            return OperationExecution(
                operation_id,
                ExecutionStatus.DENIED,
                detail="tier_3_denied_by_default",
            )

        handler = self._handlers.get(operation_id)
        if handler is None:
            return OperationExecution(
                operation_id,
                ExecutionStatus.FAILED,
                detail="operation_handler_unavailable",
            )

        if risk_tier is RiskTier.READ_ONLY:
            plan = self._operations.plan(operation_id, arguments)
            return self._invoke(plan, handler)

        if not isinstance(arguments, Mapping):
            raise TerminalPolicyError("Operation arguments must be an object.")
        ticket = self._approvals.request(operation_id, dict(arguments))
        try:
            state = self._reviewer(self._approvals, ticket.request_id)
        except Exception:
            return OperationExecution(
                operation_id,
                ExecutionStatus.FAILED,
                detail="approval_interface_unavailable",
            )

        if state is not ApprovalState.APPROVED:
            reason = state.value if isinstance(state, ApprovalState) else "invalid_state"
            return OperationExecution(
                operation_id,
                ExecutionStatus.DENIED,
                detail=f"approval_{reason}",
            )

        try:
            approved_plan = self._approvals.consume_approved(ticket.request_id)
        except ApprovalError:
            return OperationExecution(
                operation_id,
                ExecutionStatus.DENIED,
                detail="approval_unavailable_or_expired",
            )

        if approved_plan.fingerprint != ticket.plan.fingerprint:
            return OperationExecution(
                operation_id,
                ExecutionStatus.FAILED,
                detail="approved_plan_mismatch",
            )
        return self._invoke(approved_plan, handler)

    @staticmethod
    def _invoke(
        plan: OperationPlan,
        handler: OperationHandler,
    ) -> OperationExecution:
        try:
            raw_result = handler(plan.arguments)
            if not isinstance(raw_result, Mapping):
                raise TypeError("Operation results must be objects.")
            detached_mapping = dict(raw_result)
            if any(not isinstance(key, str) for key in detached_mapping):
                raise TypeError("Operation result keys must be strings.")
            serialized = json.dumps(
                detached_mapping,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
            )
            if len(serialized.encode("utf-8")) > MAX_RESULT_BYTES:
                return OperationExecution(
                    plan.operation_id,
                    ExecutionStatus.FAILED,
                    detail="operation_result_exceeds_limit",
                )
            detached_result = json.loads(serialized)
        except Exception:
            return OperationExecution(
                plan.operation_id,
                ExecutionStatus.FAILED,
                detail="operation_handler_failed",
            )

        return OperationExecution(
            plan.operation_id,
            ExecutionStatus.COMPLETED,
            result=detached_result,
        )
