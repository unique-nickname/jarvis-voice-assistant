
from dotenv import load_dotenv

load_dotenv()

from core.assistant import ask
from voice.stt import record_audio, transcribe
from voice.tts import initialize, speak, speak_async, shutdown
from voice.wake_word import wait_for_wake_word
from voice.clip_recorder import ClipRecorder
from memory import MemoryService
from terminal.operations import create_terminal_service
from tools.registry import handlers_for, tools_for
import time

import re

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

    try:
        recorder = ClipRecorder()
        terminal_service = create_terminal_service()
        assistant_tools = tools_for(memory_service, terminal_service)
        tool_handlers = handlers_for(memory_service, terminal_service)
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

            print(f"You: {text}")

            response = ask(
                text,
                tools=assistant_tools,
                tool_handlers=tool_handlers,
            )
            print(f"Jarvis: {response}")

            speak(response)

            # Let residual speaker audio and the audio pipeline settle.
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nJarvis shutting down.")

    finally:
        try:
            if recorder is not None:
                recorder.stop()
        finally:
            try:
                shutdown()
            finally:
                memory_service.close()



if __name__ == "__main__":
    main()
