
from dotenv import load_dotenv

load_dotenv()

from core.assistant import ask
from voice.stt import record_audio, transcribe
from voice.tts import initialize, speak, speak_async, shutdown
from voice.wake_word import wait_for_wake_word
import time


def main():
    initialize()
    print("Jarvis is online. Press Ctrl+C to stop.")

    try:
        while True:
            initial_audio = wait_for_wake_word()
            audio = record_audio(initial_audio=initial_audio)

            text = transcribe(audio)
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
        shutdown()
        print("\nJarvis shutting down.")


if __name__ == "__main__":
    main()
