# Jarvis

A personal voice assistant for Linux, inspired by J.A.R.V.I.S. from Iron Man.

Jarvis combines wake-word detection, speech recognition, text-to-speech, and an AI assistant capable of calling tools to interact with the desktop.

> **Status:** Work in progress. Setup instructions currently target Arch Linux. Dependencies and installation on other systems have not yet been verified.

## Features

- Wake-word detection using OpenWakeWord.
- Speech-to-text using Faster Whisper.
- AI responses and tool calling using the OpenAI API.
- Text-to-speech using Kokoro.
- Desktop application launching.
- Basic system status reporting.
- Sandboxed Linux kernel information through one fixed diagnostic tool; no general-purpose shell tool is exposed.
- Volume control for separate audio streams.
- Ability to make video clips.

Features are actively being developed, so some functionality may be incomplete.

## Requirements

- Arch Linux or a compatible Linux distribution.
- Python 3.14 for the main environment.
- Python 3.12 for the Kokoro environment.
- `uv` if Python 3.14 or Python 3.12 is not already installed.
- Git.
- Working microphone and audio output.
- An OpenAI API key.
- System audio dependencies: `portaudio` and `espeak-ng`.
- `bubblewrap` and `prlimit` (from `util-linux`) for the sandboxed kernel information tool.
- `zenity` for the local approval window used by future Tier 2 operations.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/unique-nickname/jarvis-voice-assistant.git
cd jarvis
```

### 2. Install system dependencies

On Arch Linux:

```bash
sudo pacman -S python portaudio espeak-ng git
```

For the sandboxed kernel diagnostic and approval window, install their system tools as well:

```bash
sudo pacman -S bubblewrap util-linux zenity
```

`setup.sh` checks for these executables but does not install system packages. If Bubblewrap or `prlimit` is missing, `get_kernel_info` fails closed. If Zenity is missing, the approval window cannot open. Hyprland and `hyprctl` are optional; without them, the approval window uses the compositor's normal layout.

Install `uv` if either required Python version is not already available. Follow the official instructions at https://docs.astral.sh/uv/.

The setup script uses `python3.14` and `python3.12` when available, and uses `uv` to obtain a missing version. It checks both environment versions and stops if an existing environment uses the wrong version; existing environments are not replaced automatically.

### 3. Run the setup script

```bash
chmod +x setup.sh
./setup.sh
```

The script creates or reuses two virtual environments:

- `.venv/`: Main application, using Python 3.14.
- `.venv-kokoro/`: Kokoro text-to-speech worker, using Python 3.12.

It installs dependencies from `requirements.txt` and `requirements-kokoro.txt`, creates `.env` from `.env.example` if needed, and checks for the required wake-word models.

Existing environments and an existing `.env` file are preserved. If setup reports an environment version mismatch, replace that environment with the required Python version before rerunning setup.

### 4. Configure your API key

Open `.env` in a text editor
Add your own OpenAI API key and check the model setting. Use the format provided in `.env.example`.

`TERMINAL_APPROVAL_FLOATING` controls the approval window layout. It accepts `auto`, `always`, or `never`; `auto` is the default and detects Hyprland when available. Setup adds this setting to an existing `.env` if it is missing, without changing an existing value.

### 5. Start Jarvis

Run the voice assistant with:

```bash
.venv/bin/python -m voice.assistant_loop
```

Speak the wake word, then give Jarvis a command. Press `Ctrl+C` in the terminal to stop it.

## Troubleshooting

**The setup script cannot find Python 3.12**

Install Python 3.12 or `uv`, then rerun `./setup.sh`. The script uses `uv` to obtain Python 3.12 when needed.

**The setup script cannot find Python 3.14**

Install Python 3.14 or `uv`, then rerun `./setup.sh`. The script uses `uv` to obtain Python 3.14 when needed.

**Wake-word detection does not work**

Check that all three files listed under `models/wakeword/` exist and that your microphone is working.

**Audio dependencies are missing**

On Arch Linux, install the system packages:

```bash
sudo pacman -S portaudio espeak-ng
```

**Jarvis cannot access the OpenAI API**

Check that `.env` contains a valid API key and that your account has API access and available usage.

**Dependency installation fails**

The requirements files list direct runtime dependencies and selected Kokoro compatibility pins; pip resolves their transitive dependencies. Installation has not been validated on every supported Linux distribution. Report the failing package, Python version, and environment (`.venv` or `.venv-kokoro`) when requesting help.

**The kernel information tool fails**

Check that `/usr/bin/bwrap` and `/usr/bin/prlimit` are installed. The sandbox also requires unprivileged user and network namespaces to be available. Setup warns when the executables are missing; it cannot verify that namespace restrictions are permitted by the running system.

**The approval window does not open**

Install `zenity` and run Jarvis from a graphical desktop session. Tier 2 operations remain unapproved if the local window is unavailable.

## License

No license has been specified yet. Until one is added, do not assume the repository grants permission to redistribute or reuse its code.
