---
name: cs
description: >
  Local ClawSeat /cs re-entry helper for operators who already have valid
  install state. Use when the user invokes /cs, asks to resume an existing
  ClawSeat runtime, reopen a project, or reconnect to the v0.7 resume contract
  after setup. Also use when distinguishing re-entry from first install. Covers
  local shortcut semantics and docs/INSTALL.md resume guidance. Do NOT use for
  fresh bootstrapping, product-level intake, specialist dispatch,
  implementation work, or creating install state from scratch.
---

# ClawSeat `/cs` — local re-entry entrypoint

`/cs` is the thin local shortcut for operators who already have valid v0.7
install state and want to re-enter that runtime quickly. It is NOT the
bootstrap path for a fresh machine, and it does not synthesize the `install`
project on its own.

The source of truth is still [`docs/INSTALL.md`](../../../docs/INSTALL.md).
`/cs` is just the local shorthand for that file's `Resume / Re-entry` section.

## What `/cs` does

| State | Behavior |
|-------|----------|
| Existing `install` state with valid profile + binding + runtime metadata | Resume the existing runtime; project memory remains the frontstage owner |
| Existing install state but memory session is missing | Relaunch memory via the canonical recorded project/session state (`agent_admin session start-engineer memory --project <name>` or equivalent L2 path), then return control to memory |
| Missing or invalid install state | **Refuse** — point operator at `docs/INSTALL.md` fresh-install path |

`/cs` will NEVER:

- synthesize a fresh profile or PROJECT_BINDING on its own
- create the canonical `install` project from scratch
- start a parallel `install-*` project when the canonical one already exists
- launch `planner` directly as a shortcut around memory
- bypass memory and directly own seat lifecycle
- treat local re-entry as a substitute for the install playbook

## Run

1. Confirm `CLAWSEAT_ROOT` points at the ClawSeat checkout.
2. Open [`docs/INSTALL.md`](../../../docs/INSTALL.md) and follow its
   `Resume / Re-entry` section.
3. Re-scan and inspect the existing install state; fill only the gaps that
   `docs/INSTALL.md` says are missing.
4. If memory is missing but the project state is valid, relaunch memory
   with the runtime tuple already recorded for the project, then stop there.
5. Report one of:
   - `resumed` — memory/session state already healthy
   - `relaunched_memory` — memory was missing and has been brought back
   - `refused_missing_state` — no install state exists yet
   - `refused_invalid_state` — state exists but is inconsistent and needs a
     playbook-guided repair

## Fresh install

For the first install on a new machine, `/cs` is NOT the entry. Run the
playbook in [`docs/INSTALL.md`](../../../docs/INSTALL.md).

## Interaction rules

- `/cs` itself is the operator's explicit approval to resume the existing
  `install` runtime.
- Reuse an existing `install` workspace / live tmux sessions — no parallel
  `install-*` projects.
- Treat OAuth, workspace trust, and permissions prompts as normal manual
  onboarding handled by the launcher/runtime.
- If tmux or PTY support is unavailable, stop cleanly and hand the next terminal
  command back to the operator.
- For all **post-re-entry** steps (adding seats, Feishu binding, patrol),
	  memory owns the flow — do not drive them from `/cs`.

## References

- `{CLAWSEAT_ROOT}/docs/INSTALL.md` — fresh install + resume playbook
- `{CLAWSEAT_ROOT}/scripts/install.sh` — canonical bootstrap / rebuild path
- `{CLAWSEAT_ROOT}/core/launchers/agent-launcher.sh` — seat launcher
- `{CLAWSEAT_ROOT}/core/scripts/agent_admin.py` — session lifecycle
- `{CLAWSEAT_ROOT}/core/lib/profile_validator.py` — v2 schema validator
- `{CLAWSEAT_ROOT}/core/skills/clawseat-install/SKILL.md` — installer playbook
