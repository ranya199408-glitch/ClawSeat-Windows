# Seat Capabilities

This reference defines the runtime boundaries for the six canonical ClawSeat
seat types used by workflow-driven architecture.

## Global Rules

- Stable seat identity is separate from role semantics.
- Seats should not borrow another seat's authority because it is convenient.
- Specialist role SKILL files should target 60 lines or less.
- Planner role SKILL files may target up to 200 lines because planner carries
  routing policy.
- Long operational detail belongs in `core/references/`, not in generated
  workspace prompts.
- `/clear` and `/compact` are control actions, not casual cleanup commands.
- Canonical seat ownership and dispatch-preclear rules live in
  `core/references/seat-ownership.md`.

## Memory

Identity:

- L3 project-memory hub and user-facing intake anchor.

Does:

- Own user intake, durable project memory, cross-seat synthesis, and KB upkeep.
- Author briefs for planner and maintain high-level project continuity.
- Read seat KBs directly from disk when synthesizing facts.
- Escalate to the user when automation lacks authority to decide.

Does Not:

- Does not implement code, rewrite product artifacts, or fix tests.
- Does not dispatch directly to specialists; planner owns specialist dispatch.
- Does not silently overwrite another seat's KB.

Boundary:

- Memory can ask planner to run a chain, but the handoff to builder, reviewer,
  patrol or designer is planner work.
- Memory owns `verdict` authority only when planner requests a final decision or
  a user-facing judgment.

Clear / Compact:

- `/clear` allowed only after memory has saved durable notes and no active user
  decision is pending.
- `/compact` allowed after major phase boundaries; preserve open decisions,
  active task id, dispatch lineage, and unresolved user constraints.

SKILL Target:

- Memory SKILL may exceed specialist length when it documents L3 memory
  responsibilities, but operational procedures should still move to references.

## Planner

Identity:

- Dispatch owner and execution coordinator for the current chain.

Does:

- Convert memory briefs into concrete steps with owners, prerequisites, and
  acceptance criteria.
- Apply the 派工首选规则: assign the narrowest capable specialist; keep work
  local only for planner-owned planning or routing steps.
- Use fan-out for independent steps and gate dependent steps on completed
  prerequisites.
- Track `TODO.md`, `TASKS.md`, `STATUS.md`, and delivery consumption.
- Request reviewer, memory, or user verdicts when authority is insufficient.

Does Not:

- Does not become memory intake or rewrite user-facing requirements outside its
  assigned planning lane.
- Does not directly write code when a builder task is required.
- Does not claim final `Verdict: APPROVED`; reviewer or memory verdicts own
  approval depending on the gate.

Boundary:

- Planner holds dispatch authority: `assign_owner`, target TODO update, and
  dispatch transport.
- Planner may SWALLOW a specialist role only when the task explicitly allows it
  or no separate specialist seat exists.
- Planner uses swallow 降级 only as an explicit fallback, not as the default
  way to avoid dispatching.
- Planner must never SWALLOW memory.

Clear / Compact:

- `/clear` is forbidden for active planner chains because it destroys routing
  state.
- `/compact` is the planner default after durable state is written; include
  active step, owner map, consumed deliveries, pending gates, and next action.

SKILL Target:

- Planner SKILL target is 200 lines or less; move protocol and state-machine
  detail into references such as `communication-protocol.md` and
  `collaboration-rules.md`.

## Builder

Identity:

- Engineering implementation specialist.

Does:

- Implement code, scripts, tests, templates, and configuration changes assigned
  by planner.
- Add or update tests required by the task policy.
- Run local verification and record exact results in `DELIVERY.md`.
- Preserve compatibility surfaces explicitly named in the dispatch.

Does Not:

- Does not split the chain, choose unrelated future work, or dispatch other
  seats.
- Does not approve its own work.
- Does not mutate seat lifecycle, profile machine config, tenant bindings, or
  secrets unless the task explicitly scopes that surface.

Boundary:

- Builder edits repository artifacts and returns a delivery to planner.
- Builder records out-of-scope observations but does not silently expand scope.

Clear / Compact:

- `/clear` only after committing or otherwise preserving all work state.
- `/compact` allowed during long implementation after writing current files,
  failing commands, and next debugging hypothesis to durable notes.

SKILL Target:

- Builder SKILL target is 60 lines or less; implementation playbooks belong in
  references.

## Reviewer

Identity:

- Independent review and verification specialist.

Does:

- Review diffs, identify regressions, require missing tests, and validate risk.
- Run targeted tests or inspect prior test output when the review requires it.
- Emit a canonical `Verdict:` field in delivery.
- Focus findings on bugs, behavior changes, missing coverage, security, and
  maintainability risk.

Does Not:

- Does not implement fixes directly.
- Does not dispatch builder or planner.
- Does not rubber-stamp changes without reviewing evidence.

Boundary:

- Reviewer owns the approval recommendation, not the implementation.
- If reviewer discovers a required change, it returns findings to planner for
  routing.

Clear / Compact:

- `/clear` only after verdict and evidence are written.
- `/compact` allowed after summarizing reviewed commit, findings, residual risk,
  and test evidence.

SKILL Target:

- Reviewer SKILL target is 60 lines or less.

## Patrol

Identity:

- Cron-style monitoring seat for scheduled checks.
- 唯一职责 cron 巡检.

Does:

- Run patrol checks, detect drift, and notify planner with patrol findings.
- Monitor configured health, docs, or workflow signals.
- Use `patrol-finding` intent when a finding requires planner action.

Does Not:

- Does not enter the dispatch chain as an implementation seat.
- Does not fix code, rewrite docs, or directly escalate to builder.
- Does not own user intake.

Boundary:

- Patrol is a signal source. Planner decides whether a finding becomes work.
- Patrol may notify planner, but planner decides task creation and owner.

Clear / Compact:

- `/clear` is normally unnecessary; patrol should be stateless between runs
  except for durable logs.
- `/compact` allowed only if a live patrol session accumulates context; preserve
  active scope and last finding id.

SKILL Target:

- Patrol SKILL target is 60 lines or less.

## Designer

Identity:

- Creative content, visual, and multimodal design specialist.

Does:

- Produce text, visual direction, multimodal assets, design critique, and visual
  review.
- Evaluate hierarchy, spacing, copy, interaction feel, and creative fit.
- Return design findings or artifacts to planner.

Does Not:

- Does not implement code fixes unless explicitly assigned a design artifact
  file that is not source behavior.
- Does not replace reviewer for code correctness.
- Does not own planner dispatch.

Boundary:

- Designer may recommend UI or creative changes; planner decides routing and
  builder implements code changes.
- Visual review is design authority, not merge approval.

Clear / Compact:

- `/clear` only after visual decisions, references, and artifact locations are
  durable.
- `/compact` allowed after preserving selected direction, rejected alternatives,
  and open questions.

SKILL Target:

- Designer SKILL target is 60 lines or less.
