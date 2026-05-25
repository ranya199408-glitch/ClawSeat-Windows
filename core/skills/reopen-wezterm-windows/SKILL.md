---
name: reopen-wezterm-windows
description: >
  Use when reopening visible Windows WezTerm project windows for two Windows projects.
  Do NOT use for task transport, direct WezTerm mux repair, or fresh seat resets unless explicitly requested.
related_skills: [wezterm-window]
---

# Reopen WezTerm Windows Safely

Use this skill when the operator wants the visible WezTerm windows back for the standard two projects project seats.

ClawSeat on Windows is WSL-first. WezTerm is only the display layer. Runtime, tmux sessions, and task delivery stay inside WSL.

## Golden path

Run `scripts/launch-windows.ps1` from Windows PowerShell at the ClawSeat checkout root:

```powershell
.\scripts\launch-windows.ps1 -Project project-a -NoReset
.\scripts\launch-windows.ps1 -Project project-b -NoReset
```

This creates one WezTerm window per project. Each window has panes attached through:

```bash
scripts/wait-for-seat.sh <project> <seat>
```

Expected seats are `memory`, `planner`, `builder`, `reviewer`, and `patrol`.

## Fresh restart

Only omit `-NoReset` when the operator explicitly asks for a fresh restart or reset:

```powershell
.\scripts\launch-windows.ps1 -Project project-a
.\scripts\launch-windows.ps1 -Project project-b
```

Do not reset live seats for a display-only reopen request.

## Prohibited reopen paths

Do not use `wezterm.exe start` directly for this reopen workflow.

Do not use manual `Start-Process -ArgumentList` construction for this reopen workflow.

Do not use direct `wezterm cli` commands such as `spawn`, `split-pane`, or `send-text` for this reopen workflow.

Do not use `wezterm_panes_driver.py` for this reopen workflow.

Do not use WezTerm `send-text` for task transport. ClawSeat protocol messages must use WSL/tmux transport such as `core/shell-scripts/send-and-verify.sh`.

If the GUI is still not visible after the golden path, stop and diagnose the launcher, Windows process state, and WezTerm GUI/socket state before trying another manual WezTerm command.
