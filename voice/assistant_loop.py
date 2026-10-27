
import os
import re
import time

from dotenv import load_dotenv

load_dotenv()

from core.assistant import AssistantConversation, ask
from voice.stt import record_audio, transcribe
from voice.tts import initialize, speak, shutdown
from voice.wake_word import wait_for_wake_word
from voice.clip_recorder import ClipRecorder
from memory import MemoryService
from terminal.operations import create_terminal_service
from tools.registry import handlers_for, tools_for
from tools.timers import TimerService


DEFAULT_CONVERSATION_TIMEOUT_SECONDS = 12
MAX_CONVERSATION_TIMEOUT_SECONDS = 120


def conversation_timeout_seconds() -> int:
    """Read and validate the maximum wait for a voice follow-up."""
    raw_value = os.getenv(
        "CONVERSATION_TIMEOUT_SECONDS",
        str(DEFAULT_CONVERSATION_TIMEOUT_SECONDS),
    ).strip()

    try:
        timeout = int(raw_value)
    except ValueError as exc:
        raise ValueError(
            "CONVERSATION_TIMEOUT_SECONDS must be a whole number between "
            f"1 and {MAX_CONVERSATION_TIMEOUT_SECONDS}."
        ) from exc

    if not 1 <= timeout <= MAX_CONVERSATION_TIMEOUT_SECONDS:
        raise ValueError(
            "CONVERSATION_TIMEOUT_SECONDS must be between "
            f"1 and {MAX_CONVERSATION_TIMEOUT_SECONDS}."
        )

    return timeout


def normalize_voice_command(text: str) -> str:
    """Correct likely speech-recognition errors in known voice commands."""

    text = text.strip()
    normalized = re.sub(r"[^\w\s']", "", text.casefold())
    words = normalized.split()

    if not words:
        return text

    # Accept likely misrecognitions of "clip that".
    clip_variants = {"clip", "flip", "slip", "click", "close"}

    if (
        len(words) >= 2
        and words[0] == "jarvis"
        and words[1] in clip_variants
        and words[2:] == ["that"]
    ):
        return "Clip that"

    return text


def main():
    memory_service = MemoryService()
    recorder = None
    timer_service = None

    try:
        followup_timeout = conversation_timeout_seconds()
        timer_service = TimerService()
        recorder = ClipRecorder()
        terminal_service = create_terminal_service()
        assistant_tools = tools_for(
            memory_service,
            terminal_service,
            timer_service,
        )
        tool_handlers = handlers_for(
            memory_service,
            terminal_service,
            timer_service,
        )
        initialize()
        recorder.start()
        print("Jarvis is online. Press Ctrl+C to stop.")

        while True:
            initial_audio = wait_for_wake_word()
            audio = record_audio(initial_audio=initial_audio)
            text = transcribe(audio)
            text = normalize_voice_command(text)

            if not text or text == ".":
                print("Didn't catch that.")
                continue

            conversation = AssistantConversation()

            while True:
                print(f"You: {text}")

                try:
                    response = ask(
                        text,
                        tools=assistant_tools,
                        tool_handlers=tool_handlers,
                        conversation=conversation,
                    )
                except Exception as exc:
                    print(f"[Assistant error] {exc}")
                    conversation.reset()
                    break

                print(f"Jarvis: {response}")
                playback_completed = speak(response)

                # Let residual speaker audio and the audio pipeline settle.
                time.sleep(0.5)

                if not playback_completed or not conversation.continue_listening:
                    conversation.reset()
                    break

                print(
                    "Listening for a follow-up for "
                    f"{followup_timeout} seconds..."
                )
                followup_audio = record_audio(
                    speech_start_timeout_seconds=followup_timeout,
                )

                if followup_audio.size == 0:
                    print("Follow-up window expired.")
                    conversation.reset()
                    break

                text = normalize_voice_command(transcribe(followup_audio))

                if not text or text == ".":
                    print("Didn't catch that. Returning to wake-word listening.")
                    conversation.reset()
                    break

    except KeyboardInterrupt:
        print("\nJarvis shutting down.")

    finally:
        try:
            if recorder is not None:
                recorder.stop()
        finally:
            try:
                if timer_service is not None:
                    timer_service.close()
            finally:
                try:
                    shutdown()
                finally:
                    memory_service.close()



if __name__ == "__main__":
    main()
