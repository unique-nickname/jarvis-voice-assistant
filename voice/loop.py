
from dotenv import load_dotenv

load_dotenv()

from core.assistant import ask
from voice.stt import record_audio, transcribe
from voice.tts import speak


def main():
    print("Jarvis voice mode initialized.")

    while True:
        command = input(
            "\nPress Enter to speak, or type 'q' to quit: "
        ).strip().lower()

        if command in {"q", "quit", "exit"}:
            break

        try:
            audio = record_audio(duration=5)
            text = transcribe(audio)

            if not text:
                print("No speech detected.")
                continue

            print(f"\nYou: {text}")

            response = ask(text)
            print(f"\nJarvis: {response}")

            speak(response)

        except KeyboardInterrupt:
            print("\nShutting down Jarvis.")
            break

        except Exception as exc:
            print(f"\nSomething went wrong: {exc}")


if __name__ == "__main__":
    main()
