"""Policy, approval, and routing primitives for terminal operations.

This package does not execute arbitrary commands or expose assistant tools.
"""

from terminal.approval import (
    ApprovalError,
    ApprovalQueue,
    ApprovalState,
    ApprovalTicket,
)
from terminal.approval_ui import ApprovalWindowError, review_approval
from terminal.policy import (
    ChangePreview,
    OperationDefinition,
    OperationPlan,
    OperationRegistry,
    RiskTier,
    TerminalPolicyError,
)
from terminal.service import ExecutionStatus, OperationExecution, TerminalService

__all__ = [
    "ApprovalError",
    "ApprovalQueue",
    "ApprovalState",
    "ApprovalTicket",
    "ApprovalWindowError",
    "ChangePreview",
    "ExecutionStatus",
    "OperationExecution",
    "OperationDefinition",
    "OperationPlan",
    "OperationRegistry",
    "RiskTier",
    "TerminalPolicyError",
    "TerminalService",
    "review_approval",
]
