# Claude Bundle

This bundle is the Claude Code distribution shell for ClawSeat.

Contents:

- `SKILL.md`: Claude-facing bundle declaration
- `adapter_shim.py`: minimal bootstrap wiring to `core/harness_adapter.py` and
  `adapters/harness/tmux-cli/adapter.py`

Use this bundle to load ClawSeat from Claude Code without copying core runtime
logic into the shell layer.

When the conversation is about installing or bootstrapping ClawSeat, start with
`{CLAWSEAT_ROOT}/core/skills/clawseat/SKILL.md`, then route into
`{CLAWSEAT_ROOT}/core/skills/clawseat-install/SKILL.md`. `clawseat` is the
product entry, while `/cs` is only the local convenience alias after the
runtime-side install is complete. That shortcut bootstraps or resumes the
canonical `install` project and starts `planner`.

Environment:

- set `CLAWSEAT_ROOT=/path/to/ClawSeat`
- optional: `AGENTS_ROOT`, `SESSIONS_ROOT`, `WORKSPACES_ROOT`

Project-specific behavior still comes from core/profile/adapter files under
`core/` and `adapters/projects/`.
