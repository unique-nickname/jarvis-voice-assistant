
from dotenv import load_dotenv

load_dotenv()

from core.assistant import ask
from voice.stt import record_audio, transcribe
from voice.tts import initialize, speak, speak_async, shutdown
from voice.wake_word import wait_for_wake_word
from voice.clip_recorder import ClipRecorder
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
    initialize()

    recorder = ClipRecorder()
    recorder.start()

    print("Jarvis is online. Press Ctrl+C to stop.")

    try:
        while True:
            initial_audio = wait_for_wake_word()
            audio = record_audio(initial_audio=initial_audio)

            text = transcribe(audio)

            text = normalize_voice_command(text)
            
            if not text or text == ".":
                print("Didn't catch that.")
                continue

            print(f"You: {text}")

            response = ask(text)
            print(f"Jarvis: {response}")

            speak(response)

            # Let residual speaker audio and the audio pipeline settle.
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nJarvis shutting down.")

    finally:
        recorder.stop()
        shutdown()



if __name__ == "__main__":
    main()
