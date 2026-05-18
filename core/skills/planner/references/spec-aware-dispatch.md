# Planner Spec-aware Dispatch + Rework Protocol（v0.9 草案）

When memory hands off a task that has a SPEC.md (path lives under
`~/.agents/memory/projects/<project>/spec/<task_id>/SPEC.md`), planner MUST:

1. **Read SPEC.md before workflow.md authoring**. The spec's Deliverables /
   Acceptance Criteria / Out-of-Scope sections define the contract; workflow.md
   merely decomposes how to satisfy that contract.
2. **Cross-reference AC IDs in workflow.md steps**. Each builder/reviewer step
   should declare which AC IDs it's responsible for satisfying (`covers: [AC-1, AC-3]`).
   This makes fan-in verification mechanical: every AC must be covered by ≥1 step.
3. **Pass `--spec-path` to dispatch_task.py** so the dispatch receipt records the
   spec reference. The receiving seat reads SPEC.md to understand "is this in scope".
4. **Reject scope creep**. If a delivery proposes work outside SPEC.md §5
   Out-of-Scope, planner BLOCKs that delivery and asks memory to amend the spec
   first.
5. **Forward verdicts that touch spec to memory**. `CHANGES_REQUESTED` or
   `BLOCKED` verdicts cite specific AC IDs that aren't satisfied. memory is the
   acceptance gate — planner is the dispatch gate.

## Rework Protocol (TASK_ALREADY_QUEUED 不再是死胡同)

When memory's `spec_admin.py verify` fails after planner relay, memory will
dispatch a rework via `dispatch_task.py --rework <orig_task_id> --rework-reason
"AC-N: <detail>"`. The rework receipt:

- Derives a new task_id like `<orig>-rev<N>` automatically
- Carries `parent_task_id: <orig>` for state.db / KB correlation
- Includes the failed AC list as the rework brief

planner consumes the rework like a regular dispatch (workflow.md, fan-out,
fan-in) but with explicit scope: **address only the cited AC failures**.

**Hard rule**: do NOT use `send-and-verify.sh` to communicate rework
instructions to a worker seat. send-and-verify is wake-up transport only; it
bypasses TODO / receipt / lineage tracking. If rework is needed, the path is
always `dispatch_task.py --rework`.
