import shutil
import subprocess

# Friendly names mapped to executable commands.
# Add or remove entries to match your installed applications.
ALLOWED_APPLICATIONS = {
    "zen": "zen-browser",
    "zen browser": "zen-browser",
    "browser": "zen-browser",
    "terminal": "kitty",
    "file manager": "thunar",
    "steam": "steam",
    "discord": "vesktop",
    "code editor": "code",
}


def open_application(name: str) -> dict:
    """Launch an approved desktop application."""
    name = name.strip().lower()

    executable = ALLOWED_APPLICATIONS.get(name)
    if executable is None:
        return {
            "success": False,
            "message": (
                f"'{name}' is not an approved application. "
                f"Available applications: "
                f"{', '.join(ALLOWED_APPLICATIONS)}"
            ),
        }

    # Resolve the executable without invoking a shell.
    path = shutil.which(executable)
    if path is None:
        return {
            "success": False,
            "message": (
                f"'{executable}' was not found in PATH. "
                "Check whether the application is installed."
            ),
        }

    try:
        subprocess.Popen(
            [path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        return {
            "success": True,
            "message": f"Launched {name}.",
        }

    except OSError as exc:
        return {
            "success": False,
            "message": f"Could not launch {name}: {exc}",
        }

def get_system_status() -> dict:
    """Return current CPU, memory, and battery status."""
    import psutil

    # A short interval gives CPU usage a meaningful measurement.
    cpu_percent = psutil.cpu_percent(interval=0.5)

    memory = psutil.virtual_memory()

    status = {
        "cpu_usage_percent": cpu_percent,
        "memory_usage_percent": memory.percent,
        "memory_used_gb": round(memory.used / (1024 ** 3), 2),
        "memory_total_gb": round(memory.total / (1024 ** 3), 2),
    }

    battery = psutil.sensors_battery()

    if battery is not None:
        status["battery_percent"] = battery.percent
        status["plugged_in"] = battery.power_plugged
    else:
        status["battery_percent"] = None
        status["plugged_in"] = None

    return status