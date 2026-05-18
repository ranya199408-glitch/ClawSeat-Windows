# ClawSeat Codex Bundle

This is a thin Codex distribution shell for ClawSeat.

Use it to point Codex at the core ClawSeat runtime while keeping protocol and
seat logic in `core/` and `adapters/`.

Read in this order:

1. product entry skill:
   `{CLAWSEAT_ROOT}/core/skills/clawseat/SKILL.md`
2. for installation/bootstrap requests:
   `{CLAWSEAT_ROOT}/core/skills/clawseat-install/SKILL.md`
3. first-run entry skill:
   `{CLAWSEAT_ROOT}/core/skills/cs/SKILL.md`
4. `{CLAWSEAT_ROOT}/core/skills/gstack-harness/SKILL.md`
5. project adapter skill when needed (from `{CLAWSEAT_ROOT}/adapters/projects/`)
6. `{CLAWSEAT_ROOT}/shells/codex-bundle/adapter_shim.py`

Bundle boundary:

- allowed: agent declaration, bootstrap wiring, adapter loading
- not allowed: dispatch protocol logic, handoff semantics, patrol semantics,
  workspace-contract logic

Runtime note:

- Codex uses the tmux-cli harness adapter from
  `{CLAWSEAT_ROOT}/adapters/harness/tmux-cli/adapter.py`
- adapter contract lives at `{CLAWSEAT_ROOT}/core/harness_adapter.py`
- install-time user/agent interaction rules live in
  `{CLAWSEAT_ROOT}/core/skills/clawseat-install/`
- preferred product entry is `clawseat`; `/cs` or `$cs` remain local shortcut aliases after install
