# Codex Bundle

This bundle is the Codex distribution shell for ClawSeat.

Contents:

- `AGENTS.md`: Codex-facing bundle declaration
- `adapter_shim.py`: minimal bootstrap wiring to the core adapter contract and
  tmux-cli implementation

Use this bundle to make Codex load ClawSeat as an agent configuration surface
without moving any runtime protocol into `shells/`.

Install/setup conversations should start from
`{CLAWSEAT_ROOT}/core/skills/clawseat/SKILL.md`, then route into
`{CLAWSEAT_ROOT}/core/skills/clawseat-install/SKILL.md` before loading the
runtime harness details. `clawseat` is the product entry; `/cs` is only the
local shortcut in runtimes that expose slash skills, and `$cs` is the named
shortcut where the runtime invokes local skills by name.

Environment:

- set `CLAWSEAT_ROOT=/path/to/ClawSeat`
- optional: `AGENTS_ROOT`, `SESSIONS_ROOT`, `WORKSPACES_ROOT`

Project-specific behavior remains in `core/skills/`, `core/scripts/`, and
`adapters/projects/`.
