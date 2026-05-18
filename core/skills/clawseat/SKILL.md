---
name: clawseat
description: >
  Product-level ClawSeat entrypoint for install discovery and runtime handoff
  guidance across OpenClaw, Feishu, Claude Code, and Codex contexts. Use when a
  user says ClawSeat, wants to start the product, asks how to enter the system,
  or needs the correct install versus re-entry path. Also use when routing
  first-contact product intent. Covers entrypoint selection and handoff to
  install or /cs. Do NOT use for specialist workflow execution, direct code
  changes, detailed installer flag authority, or project-specific memory
  decisions.
---

# ClawSeat

## Overview

Treat `clawseat` as the product-level entrypoint.

- In **OpenClaw / Feishu** environments, this is the canonical way to start
  ClawSeat. Do not require the user to know `/cs`.
- In **Claude Code / Codex** local runtimes, this skill points to the install
  playbook. `/cs` remains only a re-entry shortcut after install state exists.
- This skill does not implement install logic itself or claim long-lived
  runtime ownership. It routes to `clawseat-install`,
  `docs/INSTALL.md`, and the OpenClaw wrapper as needed.

## Canonical Behavior

1. Detect the host runtime.
2. Ensure the repo is cloned to a user-level directory, not inside
   `~/.openclaw/`.
3. Route to [`core/skills/clawseat-install/SKILL.md`](../clawseat-install/SKILL.md)
   and [`docs/INSTALL.md`](../../../docs/INSTALL.md).
4. Keep product framing consistent:
   - fresh install -> run the playbook
   - local re-entry -> `/cs`
   - OpenClaw bootstrap -> plugin wrapper + same playbook
5. Keep frontstage semantics consistent:
   - fresh install -> project memory is the runtime frontstage after `install.sh`
   - Feishu / OpenClaw path -> `koder` is only an optional reverse-channel
     overlay; it is not a replacement for the project memory install frontstage
6. Once project memory is prompt-ready, treat memory as the runtime owner for seat
   lifecycle and patrol. Do not invent parallel bootstrap paths.

## OpenClaw / Feishu Contract

When the user wants OpenClaw to run ClawSeat as a skill:

- prefer the OpenClaw shell/plugin path
- keep ClawSeat core logic inside the ClawSeat repo
- do not patch OpenClaw source code to implement ClawSeat behavior
- allow the user to invoke ClawSeat through natural language such as
  “安装 ClawSeat” or “启动 ClawSeat”, with this skill acting as the product
  wrapper

**Critical: clone location**

When cloning from git, install ClawSeat to a user-level directory, NOT inside
`~/.openclaw/`. ClawSeat is a standalone project, not an OpenClaw internal
component.

- Correct: `git clone <url>` in any user-level directory (e.g. home dir, projects dir)
- Wrong: `git clone <url> ~/.openclaw/workspace-clawseat` or anywhere inside `~/.openclaw/`

Then follow [`docs/INSTALL.md`](../../../docs/INSTALL.md). The canonical fresh
install path is `bash scripts/install.sh`, which performs preflight, machine
scan, provider selection, memory launch, workers window setup, and handoff to
project memory. Do not resurrect retired manual bootstrap paths.

**Critical: OpenClaw reverse-channel path**

If this skill is already running inside an OpenClaw-side `koder` overlay,
treat the current runtime as the optional reverse-channel bridge. Do not try to
spawn another `koder`, and do not rewrite the install flow around it.

- Do NOT run `start_seat.py --seat koder` — that creates a redundant tmux session
- Do NOT bootstrap a project named after yourself (e.g. `koder-frontstage`)
- The canonical project name is `install`
- The tmux-backed worker roster comes from the project's `project.toml`
  `engineers` list; minimal defaults to `planner`, `builder`, `designer`,
  while the engineering template includes `reviewer` and `patrol`
- Once project memory is prompt-ready, seat lifecycle and patrol belong to memory
- `koder` is not the install frontstage and is not part of the workers window

## Local Runtime Contract

When the host runtime is local and supports explicit skills:

- install `clawseat`, `clawseat-install`, and `cs`
- explain that `clawseat` is the fresh-install product entry
- explain that `/cs` is only the post-install re-entry shortcut
- explain that local fresh install hands off to project memory, not directly to
  `koder`

## References

- `core/skills/clawseat-install/SKILL.md`
- `core/skills/cs/SKILL.md`
- `docs/INSTALL.md`
- `shells/openclaw-plugin/README.md`
