
import os
import re
import time

from dotenv import load_dotenv

from core.config import configuration_file

load_dotenv(configuration_file())

from core.instance_lock import JarvisAlreadyRunningError, JarvisInstanceLock
from core.status import emit_runtime_status


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
    emit_runtime_status("starting")
    try:
        instance_lock = JarvisInstanceLock.acquire()
    except JarvisAlreadyRunningError as exc:
        emit_runtime_status("already_running")
        print(str(exc))
        return

    try:
        _run_assistant()
    except KeyboardInterrupt:
        print("\nJarvis shutting down.")
        emit_runtime_status("stopped")
    except Exception:
        emit_runtime_status("error")
        raise
    finally:
        instance_lock.close()


def _run_assistant():
    # Import runtime components only after acquiring the instance lock. Several
    # voice modules load models or open process-local resources at import time.
    from core.assistant import AssistantConversation, ask
    from voice.stt import record_audio, transcribe
    from voice.tts import initialize, speak, shutdown
    from voice.wake_word import wait_for_wake_word
    from voice.clip_recorder import ClipRecorder
    from memory import MemoryService
    from terminal.operations import create_terminal_service
    from tools.registry import handlers_for, tools_for
    from tools.scheduled_actions import ScheduledActionService
    from tools.timers import TimerService

    memory_service = MemoryService()
    recorder = None
    timer_service = None
    scheduled_action_service = None

    try:
        emit_runtime_status("starting")
        followup_timeout = conversation_timeout_seconds()
        timer_service = TimerService()
        recorder = ClipRecorder()
        terminal_service = create_terminal_service(
            protected_paths=memory_service.protected_paths,
        )
        scheduled_action_service = ScheduledActionService()
        assistant_tools = tools_for(
            memory_service,
            terminal_service,
            timer_service,
            scheduled_action_service,
        )
        tool_handlers = handlers_for(
            memory_service,
            terminal_service,
            timer_service,
            scheduled_action_service,
        )
        initialize()
        recorder.start()
        print("Jarvis is online. Press Ctrl+C to stop.")

        while True:
            emit_runtime_status("wake_word")
            initial_audio = wait_for_wake_word()
            emit_runtime_status("listening_command")
            audio = record_audio(initial_audio=initial_audio)
            emit_runtime_status("thinking")
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
                    emit_runtime_status("error")
                    conversation.reset()
                    break

                print(f"Jarvis: {response}")
                emit_runtime_status("speaking")
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
                emit_runtime_status("follow_up")
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
        emit_runtime_status("stopped")
        try:
            if scheduled_action_service is not None:
                scheduled_action_service.close()
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
