
from dotenv import load_dotenv

load_dotenv()

from core.assistant import ask
from memory import MemoryService
from tools.registry import handlers_for, tools_for


def main():
    memory_service = MemoryService()
    try:
        assistant_tools = tools_for(memory_service)
        tool_handlers = handlers_for(memory_service)
        print("Jarvis initialized. Type 'exit' to quit.")

        while True:
            user_input = input("\nYou: ").strip()

            if user_input.lower() in {"exit", "quit"}:
                break

            if not user_input:
                continue

            try:
                response = ask(
                    user_input,
                    tools=assistant_tools,
                    tool_handlers=tool_handlers,
                )
                print(f"\nJarvis: {response}")
            except Exception as exc:
                print(f"\nError: {exc}")

    except KeyboardInterrupt:
        print("\nJarvis shutting down.")
    finally:
        memory_service.close()


if __name__ == "__main__":
    main()
