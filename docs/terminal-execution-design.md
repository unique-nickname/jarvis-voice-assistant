# Terminal execution design

**Status:** The policy, approval queue, Zenity review window, in-process tier-routing service, Bubblewrap command runner, and one fixed Tier 1 kernel-information operation exist. The assistant has a no-argument `get_kernel_info` tool; there is no general-purpose terminal tool or privileged helper. The window can be exercised with `.venv/bin/python -m terminal.approval_demo`; this preview-only demo never executes an operation.

## Security boundary

- Future model requests must name a registered operation and provide structured JSON arguments. They must not provide shell source, executable paths, risk tiers, or their own approval result.
- Trusted application code owns each operation's argument validator, risk tier, and human-readable impact preview. An empty registry denies every proposal.
- Tier 1 operations are fixed read-only diagnostics and do not enter the approval queue. The only current operation is `system.kernel_info`, which runs `/usr/bin/uname -sr` inside the sandbox.
- Tier 2 operations require a short-lived, one-time approval from the local Zenity UI. The queued plan is immutable; changing the operation or arguments requires a new request.
- Tier 3 operations are denied by default. This foundation has no exception or override path.
- Approval state is in memory and disappears when Jarvis exits. Requests expire after 90 seconds and at most eight requests may be pending or approved at once. No command is executed by the policy or approval modules.
- `TerminalService` validates and routes plans to application-supplied Python handlers. Tier 1 handlers run directly; Tier 2 handlers run only after UI approval and one-time plan consumption; Tier 3 is denied. Handler results must be JSON objects no larger than 16 KiB. This in-process routing service is not an OS sandbox; the service and approval queue remain internal to the application.
- `BubblewrapExecutor` currently allows only `/usr/bin/uname`. It uses UID/GID 65534 inside user, PID, network, UTS, and IPC namespaces; read-only system binary/library mounts; no home-directory mount; a clean environment; `/tmp` as a 1 MiB temporary filesystem; process/resource limits through `prlimit`; a five-second wall timeout; and an 8 KiB combined output cap. If Bubblewrap or `prlimit` is unavailable or required namespace setup fails, execution fails closed. No shell is invoked.
- The assistant-facing `get_kernel_info` tool has no arguments and returns only the validated kernel name and release. It is added only when an entrypoint supplies its process-local `TerminalService`. The assistant instructions tell Jarvis to treat tool output as untrusted data.

## Approval UI contract

The UI adapter displays the operation ID, validated arguments, trusted preview, affected resources, and remaining approval time. Approve and Deny actions call `approve_from_ui` and `deny_from_ui`. Assistant tools must not receive the queue or these methods. Approval is bound to one request ID and can be consumed once; denied, expired, or consumed requests cannot be reused. The dialog uses the system-installed `zenity` executable without a shell and passes only desktop-session environment variables; if Zenity or a display is unavailable, the request remains unapproved.

`TERMINAL_APPROVAL_FLOATING` accepts `auto`, `always`, or `never` and defaults to `auto`. Auto mode checks `HYPRLAND_INSTANCE_SIGNATURE`, `XDG_CURRENT_DESKTOP`, and `XDG_SESSION_DESKTOP`. When Hyprland and `hyprctl` are available, the adapter matches the Zenity PID and fixed approval-window title, then requests floating by that window's validated address. It tries the legacy dispatcher syntax first and the Lua dispatcher syntax used by newer Hyprland versions if that fails. It does not change Hyprland configuration or target the active window. If detection or matching fails, the dialog still works using the compositor's normal layout.

The queue does not authenticate a person or secure a future UI transport. UI integration must keep approval actions local to the interactive desktop, render arguments as escaped text rather than markup, and never treat assistant output or voice transcription as the user's approval.

Because the normal voice loop is always listening, a spoken confirmation is not an approval mechanism. If the local UI is unavailable, Tier 2 work must remain pending and expire without running.

## Execution work still required

Bubblewrap and `prlimit` are system executables, not Python dependencies. `setup.sh` checks for them and warns when either is missing, but does not install system packages; the runner fails closed if either executable or the required namespace setup is unavailable. The isolation was manually checked in the current environment: the sandbox reports UID 65534, cannot read the project `.env`, and has no non-loopback network route. These checks do not replace validation on other supported Linux setups. Do not execute arbitrary Fish text, invoke `sudo`, or allow a model to approve its own plan. Add Tier 1 operations individually. Treat all command output as untrusted data and filter it for the requested purpose. Add Tier 2 operations only after the UI and sandbox are tested for their specific effects. Tier 3 remains unavailable unless a separate design is reviewed.
