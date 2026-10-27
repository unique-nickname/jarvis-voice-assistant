
from dotenv import load_dotenv

load_dotenv()

from core.instance_lock import JarvisAlreadyRunningError, JarvisInstanceLock


def main():
    try:
        instance_lock = JarvisInstanceLock.acquire()
    except JarvisAlreadyRunningError as exc:
        print(str(exc))
        return

    try:
        _run_repl()
    finally:
        instance_lock.close()


def _run_repl():
    from core.assistant import ask
    from memory import MemoryService
    from terminal.operations import create_terminal_service
    from tools.registry import handlers_for, tools_for
    from tools.scheduled_actions import ScheduledActionService
    from tools.timers import TimerService

    memory_service = MemoryService()
    timer_service = TimerService()
    scheduled_action_service = None
    try:
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
        try:
            if scheduled_action_service is not None:
                scheduled_action_service.close()
        finally:
            try:
                timer_service.close()
            finally:
                memory_service.close()


if __name__ == "__main__":
    main()
