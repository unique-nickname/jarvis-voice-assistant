"""Tests for voice conversation context and continuation decisions."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.assistant import (
    AssistantConversation,
    CONTINUE_CONVERSATION_TOOL,
    MAX_CONVERSATION_TURNS,
    ask,
)


def response(response_id: str, *, text: str = "", output=()):
    return SimpleNamespace(id=response_id, output_text=text, output=list(output))


def function_call(name: str, *, arguments: str = "{}", call_id: str = "call-1"):
    return SimpleNamespace(
        type="function_call",
        name=name,
        arguments=arguments,
        call_id=call_id,
    )


class AssistantConversationTests(unittest.TestCase):
    def test_voice_context_offers_control_and_carries_response_ids(self) -> None:
        conversation = AssistantConversation()
        supplied_tools = [{"type": "function", "name": "sample_tool"}]
        handlers = {"sample_tool": Mock(return_value={"ok": True})}
        responses = [
            response(
                "response-1",
                output=[function_call("continue_conversation")],
            ),
            response("response-2", text="Which application should I open?"),
            response("response-3", text="Firefox is open."),
        ]

        with patch(
            "core.assistant.client.responses.create",
            side_effect=responses,
        ) as create:
            first_text = ask(
                "Open an application.",
                tools=supplied_tools,
                tool_handlers=handlers,
                conversation=conversation,
            )

            self.assertEqual(first_text, "Which application should I open?")
            self.assertTrue(conversation.continue_listening)
            self.assertEqual(conversation.previous_response_id, "response-2")
            self.assertEqual(
                supplied_tools,
                [{"type": "function", "name": "sample_tool"}],
            )
            self.assertEqual(
                create.call_args_list[0].kwargs["tools"][-1],
                CONTINUE_CONVERSATION_TOOL,
            )
            self.assertEqual(
                create.call_args_list[1].kwargs["previous_response_id"],
                "response-1",
            )

            second_text = ask(
                "Firefox.",
                tools=supplied_tools,
                tool_handlers=handlers,
                conversation=conversation,
            )

        self.assertEqual(second_text, "Firefox is open.")
        self.assertFalse(conversation.continue_listening)
        self.assertEqual(conversation.previous_response_id, "response-3")
        self.assertEqual(
            create.call_args_list[2].kwargs["previous_response_id"],
            "response-2",
        )
        handlers["sample_tool"].assert_not_called()

    def test_stateless_calls_do_not_offer_or_retain_voice_control(self) -> None:
        supplied_tools = [{"type": "function", "name": "sample_tool"}]

        with patch(
            "core.assistant.client.responses.create",
            return_value=response("response-1", text="Done."),
        ) as create:
            result = ask("Do the task.", tools=supplied_tools)

        self.assertEqual(result, "Done.")
        self.assertEqual(create.call_args.kwargs["tools"], supplied_tools)
        self.assertNotIn("previous_response_id", create.call_args.kwargs)

    def test_reset_clears_context_and_continuation(self) -> None:
        conversation = AssistantConversation("response-1", True, 4)

        conversation.reset()

        self.assertIsNone(conversation.previous_response_id)
        self.assertFalse(conversation.continue_listening)
        self.assertEqual(conversation.turns_completed, 0)

    def test_final_turn_closes_conversation_without_control_tool(self) -> None:
        conversation = AssistantConversation(
            previous_response_id="response-19",
            turns_completed=MAX_CONVERSATION_TURNS - 1,
        )

        with patch(
            "core.assistant.client.responses.create",
            return_value=response("response-20", text="Completed."),
        ) as create:
            result = ask("Finish the current task.", conversation=conversation)

        request = create.call_args.kwargs
        self.assertEqual(result, "Completed.")
        self.assertNotIn(
            CONTINUE_CONVERSATION_TOOL,
            request["tools"],
        )
        self.assertIn("final turn", request["instructions"])
        self.assertEqual(conversation.turns_completed, MAX_CONVERSATION_TURNS)
        self.assertFalse(conversation.continue_listening)

    def test_fifth_tool_round_can_return_its_final_response(self) -> None:
        responses = [
            response(
                f"round-{round_number}",
                output=[
                    function_call(
                        "sample_tool",
                        call_id=f"call-{round_number}",
                    )
                ],
            )
            for round_number in range(1, 6)
        ]
        responses.append(response("final", text="All five steps are done."))
        handler = Mock(return_value={"ok": True})

        with patch(
            "core.assistant.client.responses.create",
            side_effect=responses,
        ) as create:
            result = ask(
                "Complete all steps.",
                tools=[{"type": "function", "name": "sample_tool"}],
                tool_handlers={"sample_tool": handler},
            )

        self.assertEqual(result, "All five steps are done.")
        self.assertEqual(create.call_count, 6)
        self.assertEqual(handler.call_count, 5)


if __name__ == "__main__":
    unittest.main()
