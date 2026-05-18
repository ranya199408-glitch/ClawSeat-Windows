# Collaboration Rules

This reference defines workflow behavior between ClawSeat seats. Transport and
message syntax live in `core/skills/gstack-harness/references/communication-protocol.md`.

## 1. Status 状态机 / Status State Machine

Task and step status uses this state machine:

```text
pending -> in_progress -> done
pending -> in_progress -> blocked
```

Rules:

- A step starts as `pending`.
- The assigned owner moves only its own step to `in_progress`.
- The assigned owner moves only its own step to `done` or `blocked`.
- Summary: pending -> in_progress -> done / blocked, 原子 sed 操作，只改自己
  step.
- Do not edit another owner's active step.
- Do not skip directly from `pending` to `done`.
- Do not reopen `done` without planner creating a new step or follow-up task.
- State updates must be atomic sed operations when editing Markdown task files.
- The sed range must target the current task id and current step only.
- If the sed target is ambiguous, stop and escalate instead of broad editing.
- `blocked` requires a reason and the seat that can unblock it.

Example shape:

```bash
sed -i.bak '/^### Step 2 /,/^### Step 3 / s/status: in_progress/status: done/' TODO.md
```

Use project helper scripts when available; raw sed is the fallback rule because
it makes the atomicity requirement explicit.

## 2. 派工首选规则（强制） / Dispatch Preference Rule

Planner must choose the narrowest capable owner.

Pseudocode:

```python
def assign_owner(step):
    if step.requires_user_or_memory_decision:
        return "memory"
    if step.requires_qa_browser_testing or step.requires_multimodal_ui_verification:
        return "reviewer"  # qa-only mode: find bugs, log findings, report to planner
    if step.requires_implementation:
        return "builder"
    if step.requires_code_or_artifact_review:
        return "reviewer"
    if step.requires_visual_or_creative_judgment:
        return "designer"
    if step.requires_scheduled_monitoring:
        return "patrol"
    if step.requires_planning_or_routing_only:
        return "planner"
    return "memory"  # escalation fallback, not silent execution
```

Mandatory enforcement:

- Tests for planner routing must cover builder, reviewer, designer, patrol, and
  memory escalation paths.
- Planner may keep a task local only when the step is genuinely planning,
  routing, decomposition, or receipt consumption.
- Planner must not keep implementation work local to save time.
- Planner must not send review-only work to builder.
- Planner must route browser QA testing steps to reviewer, not builder or patrol.
- Planner must not send patrol cron findings directly to builder.

## 3. Swallow Semantics

`SWALLOW=<role>` means planner temporarily acts as the swallowed role. Planner
SWALLOW=<role> 时按 swallowed seat 行事；DELIVERY schema 仍按 swallowed；
planner 永不 SWALLOW memory.

Rules:

- Planner follows the swallowed seat's boundaries while swallowed.
- DELIVERY schema remains the swallowed role schema.
- Tests and acceptance criteria remain the swallowed role criteria.
- Planner records that the role was swallowed in delivery or status.
- Planner may swallow builder, reviewer, patrol, or designer only when the
  task explicitly allows it or the seat is unavailable and the risk is accepted.
- Planner never SWALLOW memory.
- Memory authority cannot be swallowed because it includes user intake,
  escalation, and cross-project memory judgment.

When in doubt, planner dispatches instead of swallowing.

## 4. Failure / Escalation

Default `max_iterations` is 3. max_iterations 默认 3.

After three failed implementation or verification iterations, stop and escalate.

Failure mode 表:

| Failure mode | First responder | Notify | Decision owner |
| --- | --- | --- | --- |
| Command error | current owner | planner | planner unless user decision needed |
| Iteration limit exceeded | current owner | planner | planner or memory |
| Seat dead | observing seat | restart owner from watchdog rules | watchdog owner |
| User refusal | any receiver | memory | user through memory |
| Skill unavailable | current owner | planner | planner selects fallback or escalates |
| Privacy gate blocked | sender | memory | memory/user |
| Contradictory task spec | current owner | planner | planner, then memory if unresolved |
| Missing durable artifact | receiver | sender and planner | planner |
| PTY_EXHAUSTION | builder: stop + send `[BLOCKED:reason=pty-exhaustion]`; NEVER stop cross-project sessions; planner -> memory escalation | planner | memory |

Escalation message requirements:

- Identify the failed step.
- Include the exact blocker.
- Name the attempted command or action when relevant.
- Say who can decide or unblock.
- Avoid embedding secrets or private data.

## 5. 跨 step 依赖 / Cross-Step Dependencies

Planner owns dependency checks.

Rules:

- A step with prerequisites may start only after all prerequisite steps are
  `done`.
- A blocked prerequisite blocks dependent steps.
- Fan-out is allowed only for steps with no dependency path between them.
- Independent fan-out steps may be triggered concurrently.
- A fan-out result returns to planner before dependent steps start.
- Planner consumes each delivery before starting the dependent step.
- If two independent steps touch the same file or state surface, treat them as
  dependent unless write scopes are clearly disjoint.

Dependency examples:

- Reference docs can fan out from code implementation if they touch no shared
  files.
- Review depends on builder delivery.
- User verdict depends on planner summarizing the decision.
- Patrol finding triage depends on the patrol finding record.

## 6. Tool-specific 行为 / Tool-Specific Behavior

Claude / Gemini / Codex Stop hook 差异:

Claude:

- Claude Code may have a Stop hook that writes completion receipts
  automatically.
- The seat must still verify that durable delivery exists before assuming the
  hook completed.

Gemini:

- Gemini does not get the same Stop hook guarantee.
- Gemini must explicitly call `complete_handoff.py` for handoff completion.

Codex:

- Codex must explicitly call `complete_handoff.py` or the project transport
  helper for handoff completion.
- Codex should report commands and test summaries because terminal output is
  not visible to the user by default.

All tools:

- Respect the role boundary from `seat-capabilities.md`.
- Write durable state before sending protocol messages.
- Use the standard transport from `communication-protocol.md`.

## 7. 对称 watchdog / Symmetric Watchdog

The two hub seats protect each other.

- If memory is dead, planner restarts memory.
- If planner is dead, memory restarts planner.
- If both hubs are dead, external `agent-launcher` recovery takes over.
- External launcher recovery is outside this document; this doc only names the
  entry condition.
- Specialists do not independently restart hubs unless planner or memory
  explicitly assigned that recovery action.
- Patrol may report that a hub appears dead, but it does not perform the chain
  restart itself.

Restart evidence:

- Capture the missing session or failed health check.
- Record the restart command or helper used.
- Notify the recovered hub with `consumed` or `escalation` as appropriate.

> ⚠️ Restart command: MUST use `window open-engineer` (full tmux+iTerm chain).
> `session start-engineer` only respawns tmux — iTerm stays attached to dead session.
> See `core/scripts/agent_admin_commands.py::window_open_engineer` for implementation.

## 8. 派单/派工 boundary / 派单 / 派工 Boundary

This is the rules-layer version of the protocol boundary.

Memory 派单:

- Owns user intake.
- Writes or updates the brief.
- Sends the brief handoff to planner.
- Keeps final memory/user decision authority.
- Does not directly dispatch specialists.

Planner 派工:

- Reads memory's brief.
- Splits work into steps.
- Assigns owners.
- Dispatches specialists directly.
- Consumes deliveries and routes review or follow-up.
- Does not replace memory intake.

Specialists:

- Execute their assigned lane.
- Deliver to planner.
- Do not self-expand into intake, planning, or approval roles.

## assign_owner Pseudocode

Planner enforces liveness before dispatch. The available seat list is already
filtered to alive seats by `query_seat_liveness(project)`.

```python
def assign_owner(step, seats_available):
    # seats_available = query_seat_liveness(project) — alive only
    for seat in seats_available:
        if seat.role == step.owner_role:
            return seat  # 派工首选: direct dispatch
    # Not found: try restart
    if restart_seat(project, step.owner_role):
        return get_seat(project, step.owner_role)  # now alive
    # Restart failed: SWALLOW
    if step.owner_role == "memory":
        raise EscalationRequired("memory dead + restart failed → AskUserQuestion")
    return f"planner [SWALLOW={step.owner_role}]"  # planner absorbs
```

Memory is never swallowed. If memory is dead and restart fails, the workflow
must escalate to an operator-visible decision path.
