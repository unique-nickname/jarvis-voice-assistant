
#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")"

echo "=== Jarvis setup ==="

# Check the system
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required."
    exit 1
fi

# Find Python 3.12, using uv if necessary
if command -v python3.12 >/dev/null 2>&1; then
    KOKORO_PYTHON="$(command -v python3.12)"
elif command -v uv >/dev/null 2>&1; then
    uv python install 3.12
    KOKORO_PYTHON="uv run --python 3.12 python"
else
    echo "Error: Python 3.12 is required for Kokoro."
    echo "Install Python 3.12 or install uv: https://docs.astral.sh/uv/"
    exit 1
fi

# Check system dependencies
if ! command -v pacman >/dev/null 2>&1; then
    echo "Note: This script is designed for Arch Linux."
else
    for pkg in portaudio espeak-ng; do
        if ! pacman -Q "$pkg" >/dev/null 2>&1; then
            echo "System package may be needed: $pkg"
            echo "Install it with: sudo pacman -S $pkg"
        fi
    done
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

# Create environments without overwriting existing ones
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi

# Create Kokoro environment using Python 3.12
if [[ ! -x .venv-kokoro/bin/python ]]; then
    if command -v uv >/dev/null 2>&1; then
        uv python install 3.12
        uv venv --python 3.12 .venv-kokoro
    elif command -v python3.12 >/dev/null 2>&1; then
        python3.12 -m venv .venv-kokoro
    else
        echo "Error: Python 3.12 is required for Kokoro."
        echo "Install uv or Python 3.12, then rerun setup."
        exit 1
    fi
fi

# Verify versions
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

# Create or update local configuration without overwriting user values
if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
        cp .env.example .env
        echo "Created .env from .env.example."
        echo "Add your own API key to .env before running Jarvis."
    else
        echo "Warning: .env.example is missing."
    fi
elif [[ -f .env.example ]]; then
    echo "Existing .env preserved."

    # Add missing replay-buffer settings without changing existing values.
    for key in \
        CLIP_MONITOR \
        CLIP_DURATION \
        CLIP_FPS \
        CLIP_QUALITY \
        CLIP_CODEC \
        CLIP_FORMAT \
        CLIP_AUDIO \
        CLIP_DIRECTORY
    do
        if ! grep -qE "^[[:space:]]*${key}=" .env; then
            value="$(grep -E "^${key}=" .env.example | tail -n 1 || true)"

            if [[ -n "$value" ]]; then
                printf '\n%s\n' "$value" >> .env
                echo "Added missing setting: $key"
            fi
        fi
    done
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
echo "Run the voice assistant with: .venv/bin/python -m voice.assistant_loop"
