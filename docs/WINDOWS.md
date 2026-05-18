# ClawSeat Windows Port

## Overview

The Windows port is WSL-first. PowerShell is the Windows entrypoint, WSL Ubuntu is the runtime, tmux remains the seat interaction layer, and WezTerm is only the display layer that attaches to tmux sessions.

This keeps Windows close to the original ClawSeat model instead of replacing the protocol with a terminal-window API. Seat-to-seat task delivery still goes through durable ClawSeat state plus `tmux`/`send-and-verify.sh` inside WSL.

## Architecture

| Layer | Windows implementation | Responsibility |
|-------|------------------------|----------------|
| Entrypoint | PowerShell scripts | Detect dependencies, convert paths, start WSL commands, open display windows |
| Runtime | WSL Ubuntu | Run bash, Python, git, tmux, and AI CLIs |
| Display | WezTerm on Windows | Open windows that attach to existing WSL tmux sessions |
| Interaction transport | tmux inside WSL | Send prompts and wake seats through `core/shell-scripts/send-and-verify.sh` |
| Durable state | ClawSeat files under WSL paths | Keep task ledgers, receipts, sessions, and project configuration |

WezTerm must not be used for task transport. Do not use WezTerm `send-text` for ClawSeat protocol delivery; it is only for showing tmux sessions to the operator.

## Prerequisites

Install these on Windows:

1. **WSL Ubuntu**: `wsl --install -d Ubuntu`
2. **WezTerm**: `winget install wez.wezterm`

Install these inside WSL Ubuntu:

1. `bash`
2. `python3`
3. `git`
4. `tmux`
5. AI CLIs used by the selected template, such as `claude`, `codex`, or `gemini`

CLI authentication must be available inside WSL because the seat processes run there.

## Installation

Run the installer from PowerShell:

```powershell
.\scripts\install-windows.ps1 -Project myapp -Template clawseat-engineering
```

Useful options:

```powershell
# Solo template
.\scripts\install-windows.ps1 -Project myapp -Template clawseat-solo

# Creative template
.\scripts\install-windows.ps1 -Project myapp -Template clawseat-creative

# Use a specific WSL distro
.\scripts\install-windows.ps1 -Project myapp -WslDistro Ubuntu

# Dry run
.\scripts\install-windows.ps1 -Project myapp -DryRun

# Environment detection only
.\scripts\install-windows.ps1 -DetectOnly
```

`-EnableAutoPatrol` is accepted but automatic Windows scheduling is not implemented for this WSL-first port yet. Start seats through `launch-windows.ps1`.

## Launching seats

Start or resume the ClawSeat project in WSL, then open WezTerm display windows attached to tmux:

```powershell
.\scripts\launch-windows.ps1 -Project myapp
```

Options:

```powershell
# Select WSL distro
.\scripts\launch-windows.ps1 -Project myapp -WslDistro Ubuntu

# Keep existing sessions instead of resetting before launch
.\scripts\launch-windows.ps1 -Project myapp -NoReset

# Show commands without executing
.\scripts\launch-windows.ps1 -Project myapp -DryRun
```

The launcher runs `python3 core/scripts/agent_admin.py session batch-start-engineer ... --no-iterm` inside WSL, then opens one WezTerm window with vertical panes. Each pane runs `scripts/wait-for-seat.sh <project> <seat>`, which resolves canonical tmux session names through `agentctl session-name` before attaching.

## Smoke test

Use the smoke script to verify tmux delivery through `send-and-verify.sh` inside WSL:

```powershell
.\scripts\smoke-windows-tmux.ps1 -Project myapp
```

By default it probes the `builder` and `reviewer` seats, which matches `clawseat-engineering`. For `clawseat-solo` or `clawseat-creative`, pass the seats used by that project explicitly:

```powershell
.\scripts\smoke-windows-tmux.ps1 -Project myapp -Seats builder,reviewer,planner
```

A successful probe returns output beginning with `SENT:`. Anything else is treated as a failed task-delivery check.

## Operational boundaries

- PowerShell may detect dependencies, convert paths, and launch WSL commands.
- PowerShell should not send multi-line task content to seats.
- WezTerm may display tmux sessions only.
- tmux inside WSL is the only interactive seat transport.
- Durable ClawSeat files remain the source of truth for task state and receipts.

## Troubleshooting

### WSL distro not found

```powershell
wsl -l -v
wsl --install -d Ubuntu
```

Pass `-WslDistro <name>` if Ubuntu is not your default distro.

### WezTerm not found

```powershell
Get-Command wezterm.exe
winget install wez.wezterm
```

The support scripts also check the bundled `.deps\WezTerm` path when present.

### tmux not found inside WSL

```powershell
wsl -- bash -lc "command -v tmux && tmux -V"
```

Install it inside WSL Ubuntu:

```bash
sudo apt update
sudo apt install tmux
```

### Python or AI CLI not found inside WSL

```powershell
wsl -- bash -lc "command -v python3; command -v claude; command -v codex; command -v gemini"
```

Install and authenticate the required AI CLIs inside WSL, not only on Windows.

### Path conversion issues

Windows paths are converted with `wslpath`. Use `-DetectOnly` to inspect both Windows and WSL paths:

```powershell
.\scripts\install-windows.ps1 -DetectOnly
```

Paths with spaces and non-ASCII characters are supported through WSL path conversion and bash quoting.

## Development notes

When adding Windows support to a feature, preserve the WSL-first boundary:

1. Put runtime behavior in WSL-compatible Python/bash paths.
2. Use PowerShell only as an entrypoint or dependency probe.
3. Use WezTerm only to attach to tmux sessions.
4. Use `core/shell-scripts/send-and-verify.sh` for seat delivery checks.
5. Add tests that reject accidental WezTerm transport usage.

## License

Same as original ClawSeat: MIT
