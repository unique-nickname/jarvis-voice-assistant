
#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")"
PROJECT_ROOT="$PWD"

echo "=== Jarvis setup ==="

# Check system dependencies
if ! command -v pacman >/dev/null 2>&1; then
    echo "Note: This script is designed for Arch Linux."
else
    for pkg in portaudio espeak-ng tk; do
        if ! pacman -Q "$pkg" >/dev/null 2>&1; then
            echo "System package may be needed: $pkg"
            echo "Install it with: sudo pacman -S $pkg"
        fi
    done
fi

check_runtime_executable() {
    local executable_path="$1"
    local package_name="$2"
    local feature_name="$3"

    if [[ ! -x "$executable_path" ]]; then
        echo "Warning: $executable_path is missing; $feature_name will be unavailable."
        if command -v pacman >/dev/null 2>&1; then
            echo "Install it with: sudo pacman -S $package_name"
        fi
    fi
}

check_runtime_executable /usr/bin/bwrap bubblewrap "the sandboxed terminal command tool"
check_runtime_executable /usr/bin/prlimit util-linux "the sandboxed terminal command tool"
check_runtime_executable /usr/bin/fish fish "the terminal command tool"

check_optional_command() {
    local executable_name="$1"
    local feature_name="$2"

    if ! command -v "$executable_name" >/dev/null 2>&1; then
        echo "Warning: $executable_name is missing; $feature_name will be unavailable."
    fi
}

check_optional_command hyprctl "Hyprland window listing and focus tools"
check_optional_command pactl "audio output listing and selection tools"
check_optional_command parec "PipeWire/PulseAudio wake-word microphone selection"
check_optional_command wpctl "default audio volume controls"
check_optional_command playerctl "media playback controls"
check_optional_command xdg-open "opening supported files in desktop applications"
check_optional_command notify-send "desktop timer notifications"

if [[ ! -x /usr/bin/zenity && ! -x /bin/zenity ]]; then
    echo "Warning: zenity is missing; the local approval window will be unavailable."
    if command -v pacman >/dev/null 2>&1; then
        echo "Install it with: sudo pacman -S zenity"
    fi
fi

# Check GPU Screen Recorder for replay-buffer clipping
if ! command -v gpu-screen-recorder >/dev/null 2>&1; then
    echo
    echo "Warning: gpu-screen-recorder is not installed."
    echo "Jarvis will run, but replay-buffer clipping will be unavailable."

    if command -v pacman >/dev/null 2>&1; then
        if pacman -Si gpu-screen-recorder >/dev/null 2>&1; then
            echo "Install it with: sudo pacman -S gpu-screen-recorder"
        elif command -v paru >/dev/null 2>&1; then
            echo "Install it with: paru -S gpu-screen-recorder"
        elif command -v yay >/dev/null 2>&1; then
            echo "Install it with: yay -S gpu-screen-recorder"
        else
            echo "Install gpu-screen-recorder from a suitable Arch package source."
        fi
    fi
else
    echo "GPU Screen Recorder found: $(command -v gpu-screen-recorder)"
fi

check_python_version() {
    local interpreter="$1"
    local expected_version="$2"
    local actual_version

    actual_version="$("$interpreter" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

    if [[ "$actual_version" != "$expected_version" ]]; then
        echo "Error: $interpreter uses Python $actual_version; expected $expected_version."
        echo "Replace that environment with the expected Python version, then rerun setup."
        exit 1
    fi
}

# Create the main environment with Python 3.14 without replacing an existing one.
if [[ ! -x .venv/bin/python ]]; then
    if command -v python3.14 >/dev/null 2>&1; then
        python3.14 -m venv .venv
    elif command -v uv >/dev/null 2>&1; then
        uv python install 3.14
        uv venv --python 3.14 .venv
    else
        echo "Error: Python 3.14 is required for the main environment."
        echo "Install Python 3.14 or install uv: https://docs.astral.sh/uv/"
        exit 1
    fi
fi
check_python_version .venv/bin/python 3.14

# Create Kokoro environment using Python 3.12
if [[ ! -x .venv-kokoro/bin/python ]]; then
    if command -v python3.12 >/dev/null 2>&1; then
        python3.12 -m venv .venv-kokoro
    elif command -v uv >/dev/null 2>&1; then
        uv python install 3.12
        uv venv --python 3.12 .venv-kokoro
    else
        echo "Error: Python 3.12 is required for Kokoro."
        echo "Install uv or Python 3.12, then rerun setup."
        exit 1
    fi
fi
check_python_version .venv-kokoro/bin/python 3.12

.venv/bin/python --version
.venv-kokoro/bin/python --version

# Ensure pip exists in both environments
for env in .venv .venv-kokoro; do
    if ! "$env/bin/python" -m pip --version >/dev/null 2>&1; then
        "$env/bin/python" -m ensurepip --upgrade
    fi
done

# Install dependencies
if [[ -s requirements.txt ]]; then
    echo "Installing main dependencies..."
    .venv/bin/python -m pip install -r requirements.txt
else
    echo "Warning: requirements.txt is empty."
fi

if [[ -s requirements-kokoro.txt ]]; then
    echo "Installing Kokoro dependencies..."
    .venv-kokoro/bin/python -m pip install -r requirements-kokoro.txt
else
    echo "Warning: requirements-kokoro.txt is empty."
fi

# Select the same configuration path as core.config.configuration_file().
CONFIG_FILE="${JARVIS_CONFIG_FILE:-}"
if [[ -n "$CONFIG_FILE" ]]; then
    if [[ "$CONFIG_FILE" != /* ]]; then
        echo "Error: JARVIS_CONFIG_FILE must be an absolute path."
        exit 1
    fi
elif [[ -n "${XDG_CONFIG_HOME:-}" && "${XDG_CONFIG_HOME}" == /* ]]; then
    if [[ -f "$XDG_CONFIG_HOME/jarvis/.env" ]]; then
        CONFIG_FILE="$XDG_CONFIG_HOME/jarvis/.env"
    else
        CONFIG_FILE="$PROJECT_ROOT/.env"
    fi
elif [[ -f "$HOME/.config/jarvis/.env" ]]; then
    CONFIG_FILE="$HOME/.config/jarvis/.env"
else
    CONFIG_FILE="$PROJECT_ROOT/.env"
fi

CONFIG_DIRECTORY="$(dirname -- "$CONFIG_FILE")"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
if [[ "$CONFIG_HOME" != /* ]]; then
    CONFIG_HOME="$HOME/.config"
fi
if [[ -L "$CONFIG_DIRECTORY" || -L "$CONFIG_FILE" ]]; then
    echo "Error: refusing to use a symbolic link for Jarvis configuration."
    exit 1
fi
if [[ -f "$CONFIG_FILE" && ! -O "$CONFIG_FILE" ]]; then
    echo "Error: Jarvis configuration is not owned by the current user."
    exit 1
fi
if [[ "$CONFIG_DIRECTORY" != "$PROJECT_ROOT" ]]; then
    mkdir -p -- "$CONFIG_DIRECTORY"
    if [[ ! -O "$CONFIG_DIRECTORY" ]]; then
        echo "Error: Jarvis configuration directory is not owned by the current user."
        exit 1
    fi
    if [[ "$CONFIG_DIRECTORY" == "$CONFIG_HOME/jarvis" ]]; then
        chmod 700 -- "$CONFIG_DIRECTORY"
    fi
fi

# Create or update the selected configuration without overwriting user values.
if [[ ! -f "$CONFIG_FILE" ]]; then
    if [[ -f .env.example ]]; then
        cp .env.example "$CONFIG_FILE"
        chmod 600 -- "$CONFIG_FILE"
        echo "Created Jarvis configuration at $CONFIG_FILE."
        echo "Add your own OpenAI API key before running Jarvis."
    else
        echo "Warning: .env.example is missing."
    fi
elif [[ -f .env.example ]]; then
    echo "Existing configuration preserved at $CONFIG_FILE."

    # Add missing optional settings without changing existing values.
    for key in \
        JARVIS_UI_THEME \
        JARVIS_APPLICATION_ALLOWLIST \
        CONVERSATION_TIMEOUT_SECONDS \
        JARVIS_TTS_DEVICE \
        JARVIS_TTS_CPU_THREADS \
        VOICE_SILENCE_SECONDS \
        VOICE_MAX_UTTERANCE_SECONDS \
        STATUS_INDICATOR_ALWAYS_ON_TOP \
        STATUS_INDICATOR_STYLE \
        STATUS_INDICATOR_PERSISTENT \
        STATUS_INDICATOR_MONITOR \
        STATUS_INDICATOR_WIDTH \
        STATUS_INDICATOR_HEIGHT \
        TERMINAL_APPROVAL_FLOATING \
        TERMINAL_COMMANDS_ENABLED \
        TERMINAL_WRITE_ROOT \
        TERMINAL_TIER_1_OVERRIDE \
        TERMINAL_TIER_2_OVERRIDE \
        TERMINAL_TIER_3_OVERRIDE \
        CLIP_MONITOR \
        CLIP_DURATION \
        CLIP_FPS \
        CLIP_QUALITY \
        CLIP_CODEC \
        CLIP_FORMAT \
        CLIP_AUDIO \
        CLIP_DIRECTORY
    do
        if ! grep -qE "^[[:space:]]*${key}=" "$CONFIG_FILE"; then
            value="$(grep -E "^${key}=" .env.example | tail -n 1 || true)"

            if [[ -n "$value" ]]; then
                printf '\n%s\n' "$value" >> "$CONFIG_FILE"
                echo "Added missing setting: $key"
            fi
        fi
    done
fi
chmod 600 -- "$CONFIG_FILE"

if ! .venv/bin/python -c 'import tkinter' >/dev/null 2>&1; then
    echo "Warning: Tkinter is unavailable in .venv; the desktop launcher and settings window will not run."
    echo "On Arch Linux, install the Tk runtime with: sudo pacman -S tk"
    echo "The voice assistant remains available from the terminal."
fi

# Verify required wake-word models
missing=0
for model in \
    models/wakeword/jarvis.onnx \
    models/wakeword/melspectrogram.onnx \
    models/wakeword/embedding_model.onnx
do
    if [[ ! -f "$model" ]]; then
        echo "Missing model: $model"
        missing=1
    fi
done

if [[ "$missing" -ne 0 ]]; then
    echo "Some wake-word models are missing."
    echo "Jarvis cannot listen for its wake word until they are provided."
fi

echo
echo "Setup finished."
echo "Activate the main environment with: source .venv/bin/activate"
echo "Run the desktop launcher with: ./jarvis"
echo "Run without UI with: ./jarvis --headless"
echo "Run with only the status indicator: ./jarvis --indicator-only"
echo "Install application-menu entries with: .venv/bin/python -m jarvis_ui.desktop_entries install"
