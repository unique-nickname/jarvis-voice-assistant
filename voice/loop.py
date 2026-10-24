
from dotenv import load_dotenv

load_dotenv()

from core.assistant import ask
from memory import MemoryService
from tools.registry import handlers_for, tools_for
from voice.stt import record_audio, transcribe
from voice.tts import speak

# This is an older implementation of the loop with writing instead of voice. 
# Do not use this unless you want to test something specific

def main():
    memory_service = MemoryService()
    try:
        assistant_tools = tools_for(memory_service)
        tool_handlers = handlers_for(memory_service)
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

                response = ask(
                    text,
                    tools=assistant_tools,
                    tool_handlers=tool_handlers,
                )
                print(f"\nJarvis: {response}")

                speak(response)

            except KeyboardInterrupt:
                print("\nShutting down Jarvis.")
                break

            except Exception as exc:
                print(f"\nSomething went wrong: {exc}")
    except KeyboardInterrupt:
        print("\nShutting down Jarvis.")
    finally:
        memory_service.close()


if __name__ == "__main__":
    main()
