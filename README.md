# Jarvis

A personal voice assistant for Linux, inspired by J.A.R.V.I.S. from Iron Man.

Jarvis combines wake-word detection, speech recognition, text-to-speech, and an AI assistant capable of calling tools to interact with the desktop.

> **Status:** Work in progress. Setup instructions currently target Arch Linux. Dependencies and installation on other systems have not yet been verified.

## Features

- Wake-word detection using OpenWakeWord.
- Speech-to-text using Faster Whisper.
- AI responses and tool calling using the OpenAI API.
- Text-to-speech using Kokoro.
- Allowlisted desktop application launching and Hyprland window focus.
- System status reporting, including disk and OS details.
- Bounded filename search and opening supported files under the home folder.
- One-shot desktop timers while Jarvis is running.
- Delayed scheduling for selected desktop actions and generated terminal commands.
- Audio output listing and selection.
- A sandboxed Fish command tool with configurable risk tiers: the default mapping runs recognized read-only commands directly, requires local approval for modifications and unknown commands, and denies known high-risk commands.
- Volume control for separate audio streams.
- Ability to make video clips.
- A desktop launcher with a floating status indicator and a local settings window.

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
- `bubblewrap` and `prlimit` (from `util-linux`) for the sandboxed terminal tool.
- Fish for the general terminal command tool.
- `zenity` for the local approval window used by Tier 2 terminal commands.
- `notify-send` for timer notifications, `xdg-open` for supported file opening,
  and `pactl` for audio output selection.
- `wpctl` for default-volume control and `playerctl` for media control.
- `hyprctl` for window listing and focus on Hyprland; these window tools are
  unavailable on other desktop environments.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/unique-nickname/jarvis-voice-assistant.git
cd jarvis
```

### 2. Install system dependencies

On Arch Linux:

```bash
sudo pacman -S python portaudio espeak-ng git fish tk
```

For the sandboxed terminal tool and approval window, install their system tools as well:

```bash
sudo pacman -S bubblewrap util-linux zenity
```

`setup.sh` checks for these executables but does not install system packages. If Bubblewrap, `prlimit`, or Fish is missing, terminal execution fails closed. If Zenity is missing, Tier 2 commands stay unapproved. Hyprland and `hyprctl` are optional; without them, the approval window uses the compositor's normal layout.

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

It installs dependencies from `requirements.txt` and `requirements-kokoro.txt`, creates the selected config file from `.env.example` if needed, and checks for the required wake-word models.

Existing environments and an existing `.env` file are preserved. If setup reports an environment version mismatch, replace that environment with the required Python version before rerunning setup.

The desktop launcher and settings window use Tkinter from the main Python
environment; `setup.sh` checks whether it is available. The voice assistant can
still run directly from the terminal if the selected Python build has no
Tkinter support.

### 4. Configure your API key

Run `./jarvis` to open the desktop launcher, then choose **Settings** to enter
your OpenAI API key and adjust supported options. The API key field is masked;
leaving it blank preserves the saved key, and a separate checkbox clears it.
The settings window keeps unrelated lines in the config file, saves it with
user-only file permissions, and applies changes the next time Jarvis starts.
The **Applications** tab edits the friendly names and single executable paths
that the `open_application` tool may launch. It does not accept shell commands
or executable arguments. The **General** tab selects the dark or light UI theme.
The **Voice** tab controls Kokoro's compute device and the microphone's silence
and utterance limits. In **Clipping**, system audio is enabled by default and
the microphone dropdown selects no microphone, the default microphone, or a
detected input device. The app list can be refreshed and selected apps excluded.
When any app is excluded, GPU Screen Recorder switches from mixed system-output
capture to per-app capture and records all app audio except the selected apps;
this mode requires PipeWire. Turning off system audio disables desktop and app
audio while leaving the selected microphone available.

Configuration is read from `JARVIS_CONFIG_FILE` when that absolute path is set,
otherwise from `~/.config/jarvis/.env` if it exists, then from the project
`.env`. Setup uses the same selection and does not overwrite existing values.
`.env.example` remains the safe template for new configurations.

For an installed layout that keeps the Kokoro worker interpreter elsewhere,
`JARVIS_KOKORO_PYTHON` can point to its executable. If unset, Jarvis uses
`.venv-kokoro/bin/python` next to the application files.

`JARVIS_TTS_DEVICE` accepts `auto`, `cpu`, or `cuda`. `auto` lets Kokoro use
CUDA when PyTorch reports it is available; choose `cpu` to keep synthesis off
the GPU while gaming. `JARVIS_TTS_CPU_THREADS` limits PyTorch CPU threads when
the selected device is CPU (default: two). Jarvis reports the selected device
at startup. TTS audio uses a bounded chunk queue, so playback can begin before
the complete response has been synthesized.

`VOICE_SILENCE_SECONDS` controls how much silence ends an utterance (default:
two seconds, allowed range: 0.3 to 5). `VOICE_MAX_UTTERANCE_SECONDS` is the
hard recording limit for one utterance (default: 45 seconds, allowed range: 5
to 180). Both can be changed in the **Voice** settings tab or in `.env`.

`TERMINAL_APPROVAL_FLOATING` controls the approval window layout. It accepts `auto`, `always`, or `never`; `auto` is the default and detects Hyprland when available. Setup adds this setting to the selected configuration if it is missing, without changing an existing value.

The general terminal command tool is disabled by default in `.env.example`. To enable it locally, set `TERMINAL_COMMANDS_ENABLED=true`. `TERMINAL_WRITE_ROOT` sets the only user directory the sandbox can access; the template uses `~/`. Under the default tier mapping, Tier 1 commands read this directory and Tier 2 commands can write there after approval. The sandbox's `HOME` and `~` resolve to this root. The current development `.env` uses the project directory as its root, so a request for the sandbox home writes there rather than to the host home. Tool results report `access_root` and `sandbox_home` to make the destination explicit.

If terminal access is enabled, the sandbox also hides the active Jarvis memory
storage paths, even when the configured terminal root contains them.

The Terminal safety tab presents the three routing choices as **No approval**,
**Always require approval**, and **Automatically deny**. The corresponding
`TERMINAL_TIER_1_OVERRIDE`, `TERMINAL_TIER_2_OVERRIDE`, and
`TERMINAL_TIER_3_OVERRIDE` settings still store `1`, `2`, or `3`. They map the
classifier's source tier to the effective approval route; defaults (`1`, `2`,
`3`) preserve the normal policy. Routing Tier 2 or Tier 3 to **No approval**
lets commands run without a prompt with write access inside the configured
terminal root. Routing Tier 3 to **Always require approval** makes a command
eligible to run after approval. Tier overrides do not expand the filesystem
root or grant host privileges. Network access cannot be downgraded below Tier 2
approval; a mapping to Tier 3 denies it. Invalid values stop terminal-service
startup. Restart Jarvis after changing `.env`. Known credential paths and
`.env` files are masked; keep custom secrets outside the configured root.

### 5. Start Jarvis

Open the launcher:

```bash
./jarvis
```

Select **Start Jarvis**. A compact status indicator changes color as Jarvis
listens, processes a request, waits for approval, or speaks. In Settings, choose
the **pill** indicator with a short state label or a **dot** with no label. It
stays above other windows by default; its setting can be changed in the launcher.
On Hyprland, the launcher retries the float request until the indicator is
reported as floating, then pins it across workspaces by default. In Settings,
you can turn off **Show on all workspaces**, choose a monitor output, and adjust
the pill width (140–480 px) and height (22–80 px). A blank monitor setting keeps
it on the output where it starts; monitor placement and workspace pinning require
Hyprland. Closing the main window minimizes it; use **Stop Jarvis** for a clean
shutdown. The assistant process does not send transcripts or responses to the
launcher.

To run with no visible Jarvis windows while keeping the assistant running,
uncheck the status indicator and close the main window to minimize the launcher.
The launcher stays in the taskbar so you can reopen it and stop Jarvis later.

To run without the launcher or status window, use:

```bash
./jarvis --headless
```

This replaces the launcher with the voice loop in the current terminal. The
existing direct command also remains available:

```bash
.venv/bin/python -m voice.assistant_loop
```

To skip the full launcher while keeping the floating status indicator, use:

```bash
./jarvis --indicator-only
```

This starts Jarvis automatically with the main window hidden. Click the
indicator to show the launcher, or right-click it for Settings and Stop Jarvis.
Press `Ctrl+C` in the launching terminal to stop the indicator and assistant.

#### Waybar status module

Jarvis can publish its current state for a Waybar custom module. Use headless
mode so the floating Tk indicator is not shown:

```bash
./jarvis --headless
```

Add a module like this to Waybar's JSONC configuration, replacing the path
with the absolute path to this checkout:

```jsonc
"custom/jarvis": {
    "exec": "/absolute/path/to/jarvis/jarvis --waybar-status",
    "return-type": "json",
    "interval": 1,
    "format": "{text}",
    "tooltip": true
}
```

Add matching state colors to Waybar's stylesheet:

```css
#custom-jarvis { padding: 0 8px; color: #858b98; }
#custom-jarvis.wake_word,
#custom-jarvis.listening_command,
#custom-jarvis.follow_up { color: #44c7d9; }
#custom-jarvis.thinking { color: #a978ef; }
#custom-jarvis.executing { color: #ed9b48; }
#custom-jarvis.waiting_approval,
#custom-jarvis.error { color: #ff5252; }
#custom-jarvis.speaking { color: #61c784; }
```

The module displays a colored dot followed by a short state label, such as
**● Listening** or **● Approval needed**. The state class remains available for
CSS coloring, and the tooltip gives a longer description. It reads a private
status file under `~/.local/state/jarvis`; it only reports status and does not
start or stop Jarvis. Stale activity records from an exited assistant appear
as stopped. A fatal error remains visible as **Attention needed** until the next
run.

To stop other Jarvis processes from this checkout before starting a new
instance, add `--kill-existing`. It can be combined with `--headless` or
`--indicator-only`:

```bash
./jarvis --kill-existing
```

#### Hyprlauncher and desktop application entries

Hyprlauncher can launch Jarvis through its desktop finder. After running
`./setup.sh`, install per-user entries with:

```bash
.venv/bin/python -m jarvis_ui.desktop_entries install
```

The entries include the normal launcher, headless mode, indicator-only mode,
Stop, direct Settings, and restart variants for the three launch modes. The
headless entry runs without a terminal window; choose **Jarvis (Stop)** in
Hyprlauncher to stop it. Restart entries stop existing Jarvis processes from
this checkout before starting the selected mode. The Waybar status query is
intentionally not an application entry because Waybar runs it as a polling
command. All entries use the project `icon.png`; the installer registers it as
the `jarvis` icon in the user's hicolor theme so Hyprlauncher can resolve it.
If the user hicolor theme has no index file, the installer adds a marked copy
of the system hicolor index so its icon directories remain discoverable.

Entries are written under `$XDG_DATA_HOME/applications`, or
`~/.local/share/applications` if `XDG_DATA_HOME` is unset or relative. They
point to this checkout, so run the installer again if you move the project.
Restart Hyprlauncher after installing to refresh its icon-theme lookup.
Remove the entries with:

```bash
.venv/bin/python -m jarvis_ui.desktop_entries uninstall
```

The installer only replaces or removes desktop files carrying its Jarvis
ownership marker. Hyprlauncher uses desktop entries when its desktop finder is
selected (the desktop finder is the documented default); see the
[Hyprland Hyprlauncher documentation](https://wiki.hypr.land/Hypr-Ecosystem/hyprlauncher/).

You can also open the settings window directly with
`.venv/bin/python -m jarvis_ui.settings`.

Speak the wake word, then give Jarvis a command. Press `Ctrl+C` in headless mode
to stop it. In launcher mode, use **Stop Jarvis**. Only one assistant runtime
can run for the current user at a time.

Jarvis prefers a purpose-built tool when one covers the requested action. For
local facts without a matching tool, it can generate a Tier 1 read-only
terminal command. For a requested modification without a matching tool, it can
generate a Tier 2 command, which requires the local approval window. Terminal
commands are composed for the specific request; they are not pre-made command
tools. Tier 3 remains subject to the configured terminal policy.

File search returns filenames only, skips hidden folders, and stays under the
home directory. File opening is limited to supported document and media types.
Timers use desktop notifications, remain in memory only, and are cancelled
when Jarvis shuts down.

Delayed actions use a separate in-memory queue (up to 20 pending or running
actions, with a maximum delay of 30 days). The queue executes one action at a
time, so a Tier 2 approval prompt can hold later due actions until it is
approved, denied, or closed. Jarvis can queue selected
purpose-built actions or a command it generated for the specific request. The
application checks scheduled terminal commands when they are queued and again
when they are due. Tier 2 still opens the local approval window at execution
time; scheduling never counts as approval. Tier 3 follows the configured
terminal policy. Pending actions can be listed or cancelled, and every pending
action is cancelled when Jarvis shuts down; the queue does not persist across
restarts.

After a response, Jarvis listens for a follow-up when it invites a relevant
continuation. It does not add a generic "anything else" prompt to every
response. The follow-up listening window defaults to 12 seconds and can be
changed with `CONVERSATION_TIMEOUT_SECONDS` in `.env` (whole numbers from 1 to
120). When the window expires, Jarvis clears that conversation context and
returns to wake-word listening. A conversation also ends after 20 user turns to
keep its context bounded.

During a command, Jarvis ends recording after two seconds of silence by
default, or after 45 seconds even if speech continues. Change these limits with
`VOICE_SILENCE_SECONDS` and `VOICE_MAX_UTTERANCE_SECONDS` if you need longer
pauses or longer requests.

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

**The terminal command tool fails**

Check that `/usr/bin/bwrap`, `/usr/bin/prlimit`, and `/usr/bin/fish` are installed. The sandbox also requires unprivileged user and network namespaces to be available. Setup warns when executables are missing; it cannot verify that namespace restrictions are permitted by the running system.

**The approval window does not open**

Install `zenity` and run Jarvis from a graphical desktop session. Tier 2 commands remain unapproved if the local window is unavailable.

## License

No license has been specified yet. Until one is added, do not assume the repository grants permission to redistribute or reuse its code.
