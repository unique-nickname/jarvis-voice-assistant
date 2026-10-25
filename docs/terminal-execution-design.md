# Terminal execution design

**Status:** The non-executing policy, approval queue, and a Zenity review window exist. Jarvis still has no terminal execution tool, shell runner, or privileged helper. The window can be exercised with `.venv/bin/python -m terminal.approval_demo`; this preview-only demo never executes an operation.

## Security boundary

- Future model requests must name a registered operation and provide structured JSON arguments. They must not provide shell source, executable paths, risk tiers, or their own approval result.
- Trusted application code owns each operation's argument validator, risk tier, and human-readable impact preview. An empty registry denies every proposal.
- Tier 1 operations are fixed read-only diagnostics and do not enter the approval queue.
- Tier 2 operations require a short-lived, one-time approval from the local Zenity UI. The queued plan is immutable; changing the operation or arguments requires a new request.
- Tier 3 operations are denied by default. This foundation has no exception or override path.
- Approval state is in memory and disappears when Jarvis exits. Requests expire after 90 seconds and at most eight requests may be pending or approved at once. No command is executed by the policy or approval modules.

## Approval UI contract

The UI adapter displays the operation ID, validated arguments, trusted preview, affected resources, and remaining approval time. Approve and Deny actions call `approve_from_ui` and `deny_from_ui`. Assistant tools must not receive the queue or these methods. Approval is bound to one request ID and can be consumed once; denied, expired, or consumed requests cannot be reused. The dialog uses the system-installed `zenity` executable without a shell and passes only desktop-session environment variables; if Zenity or a display is unavailable, the request remains unapproved.

`TERMINAL_APPROVAL_FLOATING` accepts `auto`, `always`, or `never` and defaults to `auto`. Auto mode checks `HYPRLAND_INSTANCE_SIGNATURE`, `XDG_CURRENT_DESKTOP`, and `XDG_SESSION_DESKTOP`. When Hyprland and `hyprctl` are available, the adapter matches the Zenity PID and fixed approval-window title, then requests floating by that window's validated address. It tries the legacy dispatcher syntax first and the Lua dispatcher syntax used by newer Hyprland versions if that fails. It does not change Hyprland configuration or target the active window. If detection or matching fails, the dialog still works using the compositor's normal layout.

The queue does not authenticate a person or secure a future UI transport. UI integration must keep approval actions local to the interactive desktop, render arguments as escaped text rather than markup, and never treat assistant output or voice transcription as the user's approval.

Because the normal voice loop is always listening, a spoken confirmation is not an approval mechanism. If the local UI is unavailable, Tier 2 work must remain pending and expire without running.

## Execution work still required

Before registering any operation, add a separate executor with an unprivileged identity, explicit filesystem and network boundaries, clean environment, fixed working directory, process and output limits, and timeout handling. Verify sandbox enforcement on the target Linux setup. Do not execute arbitrary Fish text, invoke `sudo`, or allow a model to approve its own plan. Add Tier 1 operations individually; add Tier 2 only after the UI and sandbox are tested. Tier 3 remains unavailable unless a separate design is reviewed.
