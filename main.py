
from dotenv import load_dotenv

load_dotenv()

from core.assistant import ask


def main():
    print("Jarvis initialized. Type 'exit' to quit.")

    while True:
        try:
            user_input = input("\nYou: ").strip()

            if user_input.lower() in {"exit", "quit"}:
                break

            if not user_input:
                continue

            response = ask(user_input)
            print(f"\nJarvis: {response}")

        except KeyboardInterrupt:
            print("\nJarvis shutting down.")
            break

        except Exception as exc:
            print(f"\nError: {exc}")


if __name__ == "__main__":
    main()
