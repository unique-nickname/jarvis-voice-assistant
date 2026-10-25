"""Policy and approval primitives for a future terminal executor.

This package deliberately does not execute processes or expose assistant tools.
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

__all__ = [
    "ApprovalError",
    "ApprovalQueue",
    "ApprovalState",
    "ApprovalTicket",
    "ApprovalWindowError",
    "ChangePreview",
    "OperationDefinition",
    "OperationPlan",
    "OperationRegistry",
    "RiskTier",
    "TerminalPolicyError",
    "review_approval",
]
