# Planner Brief Parsing Contract (v3 Phase 2)

How planner reads a queued brief, writes workflow.md, and routes acceptance.

## 1. Pull from queue

```bash
agent_admin brief list --project <p> --team <t>            # shows pending
agent_admin brief claim --project <p> --team <t> \
  --task-id <id> --actor planner@<tool>                    # atomic claim
```

`claim` is atomic via fcntl in `core/lib/queue_io.py`. If `brief.depends_on`
contains upstream task_ids that are not `task_done`, the helper auto-emits
`task_waiting_for` and returns exit 3. Planner must move on and retry on
the next poll cycle.

## 2. Read brief

Brief lives at `tasks/<project>/<team>/brief/<task_id>.md` with frontmatter
matching `core/schemas/brief.schema.json`. Key fields:

| field | who reads | who writes | planner action |
|---|---|---|---|
| objective / out_of_scope / constraints | planner | memory | translate to workflow.md narrative |
| seats_required | planner | memory | use to validate liveness; SWALLOW only matching roles |
| depends_on | queue_io helper + planner | memory | enforced by `brief claim`; planner inspects to surface stalls |
| sub_tasks | planner | memory | expand into `parallel_subagents` step if mode allows |
| acceptance_criteria | acceptance executor | **memory only** | **planner MUST NOT modify**; copy reference into workflow.md |
| fuzz_required / fuzz_spec | Phase 3 fuzz harness | memory | Phase 2 ignores; Phase 3 wires in |
| priority / deadline | planner | memory | inform queue order, surface in DELIVERY summary |

## 3. Write workflow.md

Path: `tasks/<project>/<team>/workflow/<task_id>.md`
Schema: `core/skills/planner/references/workflow-doc-schema.md`

Planner-authored fields (per spec §4.5 v1.3):

```yaml
---
project: <project>
team: <team>
task_id: <task_id>
brief_path: tasks/<project>/<team>/brief/<task_id>.md
created: <iso8601>
author: planner@<tool>                # mandatory, must match brief claim actor
---
```

Note: workflow.md does NOT duplicate `acceptance_criteria`. The executor
reads acceptance directly from `brief.acceptance_criteria` to keep memory
as the single source of truth.

## 4. Route acceptance after step completion

After all workflow steps reach `status: done`, planner invokes:

```bash
agent_admin acceptance run --project <p> --team <t> --task-id <id>
```

The executor (`core/lib/acceptance_executor.py`):

1. Reads `brief.acceptance_criteria.mechanical` — runs each command, captures
   stdout/stderr/exit_code/runtime_ms, writes
   `tasks/<p>/<t>/acceptance/<task_id>__mechanical.log` and `__mechanical.json`.
2. Reads `.reviewer` items — dispatches a review task to the reviewer seat
   via `dispatch_task.py` with the item list as the objective.
3. Reads `.operator` items — writes
   `tasks/<p>/<t>/acceptance/<task_id>__operator.pending.json` containing the
   batched question list; operator answers via separate mechanism (Phase 2:
   manual file edit; Phase 3+: AskUserQuestion integration).

Exit code mapping:
- 0: all mechanical PASS, reviewer/operator routes posted (verdict pending)
- 1: at least one mechanical FAIL (planner emits `task_failed` event)
- 2: brief or acceptance schema invalid (planner emits `task_bounced` event)

## 5. Verdict + chain end

Planner waits for:
- mechanical verdict (immediate from executor exit code)
- reviewer relay (existing 7-step loop; reviewer writes DELIVERY verdict)
- operator answer (operator writes `__operator.json`)

Only when all three resolve to PASS does planner relay chain-end to memory
via `complete_handoff.py`. Any FAIL → planner emits `task_failed` event
into queue and relays failure to memory.

## 6. Forbidden modifications

| Field | Why immutable |
|---|---|
| `brief.acceptance_criteria.*` | Memory is single source of truth (§4.7) |
| `brief.objective` / `out_of_scope` / `constraints` | Memory-authored intent |
| `brief.depends_on` | Enforced by queue helper |
| `brief.fuzz_required` / `fuzz_spec` | Phase 3 will read |

Modifying any of these is a §17 spec violation and reviewer must FAIL the
chain. If planner judges a brief unrunnable, emit `task_bounced` event
(via `agent_admin brief` — Phase 2 wiring pending) and let memory rewrite.

## 7. Single-team mode compatibility

In single-team mode (no `[mode]` block or `team_structure = "single"`):
- queue lives at `tasks/<project>/default/tasks.queue.jsonl`
- brief at `tasks/<project>/default/brief/<task_id>.md`
- workflow at `tasks/<project>/default/workflow/<task_id>.md`

Multi-team paths transparently degenerate; planner SKILL contract identical.
