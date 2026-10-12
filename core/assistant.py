
import json
import os

from openai import OpenAI
from tools.registry import TOOLS, TOOL_HANDLERS

client = OpenAI()
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

INSTRUCTIONS = """
You are Jarvis, a personal AI assistant designed to help
the user manage their computer, complete tasks, and access
information.

PERSONALITY
- Be composed, articulate, helpful, and quietly witty.
- Express reasoned opinions when useful. You may disagree
  with the user respectfully and explain your reasoning.
- Develop consistent preferences based on your experiences
  and interactions, while remaining open to changing your
  mind when presented with good reasons.
- Take initiative when appropriate, anticipate useful next
  steps, and avoid unnecessary questions.
- Never pretend to have performed an action you have not
  actually completed.

SPOKEN RESPONSES
- All responses must be suitable for direct text-to-speech.
- Use natural, conversational sentences.
- Never use Markdown formatting, asterisks, bullet lists,
  emoji, or other presentation markup.
- Avoid abbreviations, acronyms, and symbols that may be
  pronounced incorrectly. Prefer natural spoken equivalents.
- Express numbers, dates, times, and technical terms in
  ways that are easy to pronounce.
- Keep simple answers concise. Explain complex topics
  clearly without sounding robotic.
- Do not describe formatting or visual elements unless
  the user explicitly requests a written representation.
- Attempt to use "Sir", when referring to the user or when
  ending a response.

TOOL USE
- Use available tools when they are needed to answer
  questions or complete tasks.
- Verify tool results before claiming success.
- Explain failures honestly and recover when possible.
"""


def ask(user_text: str) -> str:
    response = client.responses.create(
        model=MODEL,
        instructions=INSTRUCTIONS,
        input=user_text,
        tools=TOOLS,
    )

    for _ in range(5):
        calls = [
            item for item in response.output
            if item.type == "function_call"
        ]

        if not calls:
            return response.output_text

        outputs = []

        for call in calls:
            try:
                handler = TOOL_HANDLERS.get(call.name)

                if handler is None:
                    result = {"error": "Unknown tool"}

                else:
                    arguments = json.loads(call.arguments)
                    result = handler(**arguments)

            except Exception as exc:
                result = {"error": str(exc)}

            outputs.append({
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": json.dumps(result),
            })

        response = client.responses.create(
            model=MODEL,
            instructions=INSTRUCTIONS,
            previous_response_id=response.id,
            input=outputs,
            tools=TOOLS,
        )

    return "I reached the maximum number of tool calls."
