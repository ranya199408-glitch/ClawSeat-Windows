---
name: clawseat-claude-bundle
description: Thin Claude Code bundle for loading ClawSeat through the core gstack harness skill plus a project adapter skill, while delegating runtime/session behavior to the tmux-cli harness adapter.
---

# ClawSeat Claude Bundle

`clawseat-claude-bundle` is a distribution shell.

It does not implement ClawSeat protocol logic. It only wires Claude Code to:

- product entry skill:
  - `{CLAWSEAT_ROOT}/core/skills/clawseat/SKILL.md`
- first-run entry skill:
  - `{CLAWSEAT_ROOT}/core/skills/cs/SKILL.md`
- install/bootstrap entry skill:
  - `{CLAWSEAT_ROOT}/core/skills/clawseat-install/SKILL.md`
- core harness skill:
  - `{CLAWSEAT_ROOT}/core/skills/gstack-harness/SKILL.md`
- optional project adapter skill (from `{CLAWSEAT_ROOT}/adapters/projects/`)
- tmux-backed harness adapter shim:
  - `{CLAWSEAT_ROOT}/shells/claude-bundle/adapter_shim.py`

## Use

1. Export `CLAWSEAT_ROOT=/path/to/ClawSeat`
2. Install the entry skills with `python3 "$CLAWSEAT_ROOT/core/skills/clawseat-install/scripts/install_entry_skills.py"`
3. Treat `{CLAWSEAT_ROOT}/core/skills/clawseat/SKILL.md` as the product entrypoint
4. Tell the user to run `/cs` only when they want the local shortcut after install
5. For manual install/bootstrap requests, load `{CLAWSEAT_ROOT}/core/skills/clawseat-install/SKILL.md`
6. Load the core skill at `{CLAWSEAT_ROOT}/core/skills/gstack-harness/SKILL.md`
7. Load the project adapter skill when the project has one
8. Use `adapter_shim.py` only for minimal tmux-cli adapter bootstrap

## Boundary

This shell may:

- declare Claude Code entry metadata
- point Claude Code at core and adapter paths
- construct a tmux-cli `HarnessAdapter`

This shell must not:

- define planner / koder / handoff semantics
- reimplement dispatch, completion, patrol, or seat contracts
- fork core runtime logic into the shell layer
