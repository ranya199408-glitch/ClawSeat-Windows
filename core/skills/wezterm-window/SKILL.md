---
name: wezterm-window
description: >
  Windows display helpers for the WSL-first ClawSeat port. WezTerm is display-only;
  runtime and task delivery stay inside WSL tmux via send-and-verify.sh.
related_skills: [tmux-basics]
---

# WezTerm Display Management (Windows)

The Windows port is WSL-first:

- PowerShell is the Windows entrypoint.
- WSL Ubuntu runs bash, Python, tmux, git, and AI CLIs.
- WezTerm only displays WSL tmux sessions.
- Task delivery must use `core/shell-scripts/send-and-verify.sh` inside WSL.

Do not use WezTerm pane text injection for ClawSeat protocol messages. Do not launch AI CLIs directly from Windows PowerShell for seats.

## Launch seats

Use the supported launcher:

```powershell
.\scripts\launch-windows.ps1 -Project myproject
```

The launcher starts the project in WSL and opens WezTerm windows that run:

```bash
scripts/wait-for-seat.sh <project> <seat>
```

`wait-for-seat.sh` resolves canonical tmux session names through `agentctl session-name` before attaching.

## Send a probe message

Use WSL tmux transport, not WezTerm pane injection:

```powershell
.\scripts\smoke-windows-tmux.ps1 -Project myproject -Seats builder,reviewer
```

For a single message from helper scripts, use:

```powershell
.\core\skills\wezterm-window\scripts\Send-ClawSeatCommand.ps1 `
  -Project myproject `
  -Seat builder `
  -Command "hello from Windows smoke"
```

The helper delegates to WSL `send-and-verify.sh`.

## Compatibility wrappers

These scripts are retained as WSL-first wrappers for old callers:

- `core/skills/wezterm-window/scripts/Start-ClawSeatWindow.ps1`
- `core/skills/wezterm-window/scripts/Start-ClaudeAgent.ps1`

They delegate to `scripts/launch-windows.ps1` instead of starting AI CLIs directly.
