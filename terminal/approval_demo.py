"""Open a harmless approval-window preview without executing any operation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dotenv import load_dotenv

from terminal.approval import ApprovalQueue, ApprovalState
from terminal.approval_ui import ApprovalWindowError, review_approval
from terminal.policy import ChangePreview, OperationDefinition, OperationRegistry, RiskTier

load_dotenv()


def _validate_demo_arguments(arguments: Mapping[str, Any]) -> None:
    if arguments != {"example": "preview-only"}:
        raise ValueError("The demo accepts only its fixed preview argument.")


def _build_demo_preview(arguments: Mapping[str, Any]) -> ChangePreview:
    return ChangePreview(
        title="Preview-only approval test",
        description=(
            "This demo only tests the approval buttons. It will not change files, "
            "settings, or services, and it will not run a command."
        ),
        affected_resources=("No resources; preview only",),
    )


def main() -> int:
    operations = OperationRegistry(
        (
            OperationDefinition(
                operation_id="demo.preview-only",
                risk_tier=RiskTier.MODIFICATION,
                validate_arguments=_validate_demo_arguments,
                build_preview=_build_demo_preview,
            ),
        )
    )
    queue = ApprovalQueue(operations)
    ticket = queue.request("demo.preview-only", {"example": "preview-only"})

    try:
        state = review_approval(queue, ticket.request_id)
    except ApprovalWindowError as exc:
        print(f"Approval window unavailable: {exc}")
        return 1

    print(f"Preview complete. Approval state: {state.value}. No operation was run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
