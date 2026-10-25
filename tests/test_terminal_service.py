"""Tests for risk-tier routing without real system side effects."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from terminal import (
    ApprovalState,
    ChangePreview,
    ExecutionStatus,
    OperationDefinition,
    OperationRegistry,
    RiskTier,
    TerminalPolicyError,
    TerminalService,
)


def _validate_empty(arguments: dict[str, object]) -> None:
    if arguments:
        raise TerminalPolicyError("This operation takes no arguments.")


def _validate_target(arguments: dict[str, object]) -> None:
    if set(arguments) != {"target"} or arguments["target"] != "workspace":
        raise TerminalPolicyError("Unsupported target.")


def _preview(arguments: dict[str, object]) -> ChangePreview:
    return ChangePreview(
        title="Review a workspace change",
        description="Apply the requested change to the workspace.",
        affected_resources=("workspace",),
    )


def _tier_three_must_not_run(arguments: dict[str, object]) -> ChangePreview:
    raise AssertionError("Tier 3 plans must not be built.")


class TerminalServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.operations = OperationRegistry(
            (
                OperationDefinition(
                    operation_id="system.inspect",
                    risk_tier=RiskTier.READ_ONLY,
                    validate_arguments=_validate_empty,
                    build_preview=lambda arguments: ChangePreview(
                        title="Read system status",
                        description="Return a fixed, read-only status result.",
                    ),
                ),
                OperationDefinition(
                    operation_id="workspace.update",
                    risk_tier=RiskTier.MODIFICATION,
                    validate_arguments=_validate_target,
                    build_preview=_preview,
                ),
                OperationDefinition(
                    operation_id="system.privileged-change",
                    risk_tier=RiskTier.HIGH_RISK,
                    validate_arguments=_validate_empty,
                    build_preview=_tier_three_must_not_run,
                ),
            )
        )
        self.inspect_handler = Mock(return_value={"status": "healthy"})
        self.update_handler = Mock(return_value={"changed": True})
        self.tier_three_handler = Mock(return_value={"changed": True})
        self.handlers = {
            "system.inspect": self.inspect_handler,
            "workspace.update": self.update_handler,
            "system.privileged-change": self.tier_three_handler,
        }

    def test_tier_one_runs_handler_without_approval(self) -> None:
        reviewer = Mock(side_effect=AssertionError("Tier 1 must not prompt."))
        service = TerminalService(self.operations, self.handlers, reviewer=reviewer)

        response = service.execute("system.inspect", {})

        self.assertEqual(response.status, ExecutionStatus.COMPLETED)
        self.assertEqual(response.as_dict()["result"], {"status": "healthy"})
        self.inspect_handler.assert_called_once_with({})
        reviewer.assert_not_called()

    def test_tier_two_runs_once_only_after_approval_is_consumed(self) -> None:
        approved_request: dict[str, object] = {}

        def approve(queue, request_id: str) -> ApprovalState:
            approved_request["queue"] = queue
            approved_request["request_id"] = request_id
            queue.approve_from_ui(request_id)
            return ApprovalState.APPROVED

        service = TerminalService(self.operations, self.handlers, reviewer=approve)

        response = service.execute("workspace.update", {"target": "workspace"})

        self.assertEqual(response.status, ExecutionStatus.COMPLETED)
        self.assertEqual(response.result, {"changed": True})
        self.update_handler.assert_called_once_with({"target": "workspace"})
        queue = approved_request["queue"]
        request_id = approved_request["request_id"]
        self.assertEqual(queue.state(request_id), ApprovalState.CONSUMED)

    def test_denied_tier_two_request_never_runs_handler(self) -> None:
        def deny(queue, request_id: str) -> ApprovalState:
            return queue.deny_from_ui(request_id).state

        service = TerminalService(self.operations, self.handlers, reviewer=deny)

        response = service.execute("workspace.update", {"target": "workspace"})

        self.assertEqual(response.status, ExecutionStatus.DENIED)
        self.assertEqual(response.detail, "approval_denied")
        self.update_handler.assert_not_called()

    def test_failed_or_invalid_reviewer_never_runs_handler(self) -> None:
        for reviewer in (
            Mock(side_effect=RuntimeError("desktop unavailable")),
            Mock(return_value="approved"),
        ):
            with self.subTest(reviewer=reviewer):
                handler = Mock(return_value={"changed": True})
                service = TerminalService(
                    self.operations,
                    {"workspace.update": handler},
                    reviewer=reviewer,
                )

                response = service.execute(
                    "workspace.update",
                    {"target": "workspace"},
                )

                self.assertIn(
                    response.status,
                    (ExecutionStatus.FAILED, ExecutionStatus.DENIED),
                )
                handler.assert_not_called()

    def test_tier_three_is_denied_without_validation_or_handler_call(self) -> None:
        service = TerminalService(self.operations, self.handlers)

        response = service.execute("system.privileged-change", {})

        self.assertEqual(response.status, ExecutionStatus.DENIED)
        self.assertEqual(response.detail, "tier_3_denied_by_default")
        self.tier_three_handler.assert_not_called()

    def test_missing_handler_fails_without_prompting(self) -> None:
        reviewer = Mock(side_effect=AssertionError("Missing handler must fail first."))
        service = TerminalService(self.operations, {}, reviewer=reviewer)

        response = service.execute("workspace.update", {"target": "workspace"})

        self.assertEqual(response.status, ExecutionStatus.FAILED)
        self.assertEqual(response.detail, "operation_handler_unavailable")
        reviewer.assert_not_called()

    def test_bad_or_oversized_handler_results_are_not_returned(self) -> None:
        bad_results = (
            Mock(return_value={"value": object()}),
            Mock(return_value={"value": "x" * 16_385}),
            Mock(return_value=["not", "an", "object"]),
        )
        for handler in bad_results:
            with self.subTest(handler=handler):
                service = TerminalService(
                    self.operations,
                    {"system.inspect": handler},
                )

                response = service.execute("system.inspect", {})

                self.assertEqual(response.status, ExecutionStatus.FAILED)
                self.assertIn(
                    response.detail,
                    {"operation_handler_failed", "operation_result_exceeds_limit"},
                )

    def test_handler_exceptions_are_returned_as_generic_errors(self) -> None:
        handler = Mock(side_effect=RuntimeError("private path or secret"))
        service = TerminalService(self.operations, {"system.inspect": handler})

        response = service.execute("system.inspect", {})

        self.assertEqual(response.status, ExecutionStatus.FAILED)
        self.assertEqual(response.detail, "operation_handler_failed")
        self.assertNotIn("private path or secret", str(response.as_dict()))

    def test_serialized_result_stays_bounded_after_caller_mutation(self) -> None:
        service = TerminalService(
            self.operations,
            {"system.inspect": Mock(return_value={"status": "healthy"})},
        )
        response = service.execute("system.inspect", {})
        self.assertIsNotNone(response.result)
        response.result["status"] = "x" * 16_385

        with self.assertRaisesRegex(ValueError, "size limit"):
            response.as_dict()


if __name__ == "__main__":
    unittest.main()
