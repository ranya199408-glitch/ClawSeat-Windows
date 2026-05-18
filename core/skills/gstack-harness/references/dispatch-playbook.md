# Dispatch Playbook

Use this when you want the lowest-freedom, most repeatable command path.

Prefer these helpers over hand-written `TODO.md`, `TASKS.md`, or `STATUS.md`
edits.

When you must use `<repo-root>/core/shell-scripts/send-and-verify.sh` directly in a
multi-project environment:

- prefer the canonical session name, for example `<project>-planner-<tool>`
- otherwise pass `--project <project>`
- do not use a bare seat id like `planner` without project context

## Frontstage -> planner

```bash
python3 <repo-root>/core/skills/gstack-harness/scripts/dispatch_task.py \
  --profile <project-profile.toml> \
  --source koder \
  --target planner \
  --task-id <TASK_ID> \
  --title '<TITLE>' \
  --objective '<OBJECTIVE>' \
  --test-policy UPDATE \
  --reply-to koder
```

## Planner -> specialist

```bash
python3 <repo-root>/core/skills/gstack-harness/scripts/dispatch_task.py \
  --profile <project-profile.toml> \
  --source planner \
  --target builder-1 \
  --task-id <TASK_ID> \
  --title '<TITLE>' \
  --objective '<OBJECTIVE>' \
  --test-policy UPDATE \
  --reply-to planner
```

Swap `--target` for `reviewer-1`, `patrol-1`, or `designer-1` as needed.
When a Feishu group is configured, the dispatch helper only posts the planner
release broadcast when legacy group broadcasting is explicitly enabled. That
legacy path is opt-in, not the default control packet for koder-facing routing.

That release broadcast is only group-visible telemetry. Do not use it as the
control packet that `koder` parses for automated routing.

## Fan-out hint for multi-part tasks

When a `planner -> specialist` task has 2+ independent sub-parts, the
dispatch `--objective` (or the linked task file body) must explicitly include
a fan-out hint. This tells the specialist to parallelize via sub-agents
instead of serializing.

Template line to include in the objective or task body:

> "This task has <N> independent sub-parts (Part A: <scope>; Part B: <scope>
> [...]). Fan them out to sub-agents using your agent-dispatch primitive
> (Claude `Agent` tool, Codex subagent, Gemini subagent). Serialize only the
> final cross-check and single DELIVERY write-up. The full pattern is
> summarized in this playbook."

See this playbook for the trigger rules and anti-patterns.

## Specialist -> planner completion

```bash
python3 <repo-root>/core/skills/gstack-harness/scripts/complete_handoff.py \
  --profile <project-profile.toml> \
  --source builder-1 \
  --target planner \
  --task-id <TASK_ID> \
  --title '<TITLE>' \
  --summary '<DELIVERY_SUMMARY>'
```

Reviewer completion must add `--verdict APPROVED` (or another canonical
verdict).

## Review gate

If a task changes docs, templates, skills, protocol text, config, or source
code, planner must not close it out directly after a single review-free pass.
The safe default is:

1. planner routes the implementation to `builder-1` when code or files need
   to change
2. planner routes the resulting artifact to `reviewer-1`
3. only after the reviewer verdict lands may planner send the frontstage
   closeout

Pure audit or analysis tasks may skip the review lane only when the task spec
explicitly says it is review-free.

## Planner consumes specialist completion

After reading the specialist delivery, stamp the durable ACK before routing the
next hop:

```bash
python3 <repo-root>/core/skills/gstack-harness/scripts/complete_handoff.py \
  --profile <project-profile.toml> \
  --source builder-1 \
  --target planner \
  --task-id <TASK_ID> \
  --ack-only
```

That `Consumed:` ACK only records that the specialist delivery was read. It
does not mean the chain is finished. If the reviewer verdict resolves the
task, planner must immediately continue with the frontstage closeout helper
and emit the `planner -> koder` receipt; do not leave the chain parked after
`ack-only`.

If the receipt is part of the planner's group-visible chain, the completion
helper only emits the matching Feishu group broadcast when
`CLAWSEAT_ENABLE_LEGACY_FEISHU_BROADCAST=1` (or the OpenClaw equivalent) is
set. Otherwise it stays on the user-identity `OC_DELEGATION_REPORT_V1`
closeout path.

When the receiver is frontstage / `koder` and the group bridge uses user
identity, prefer the dedicated helper:

```bash
python3 <repo-root>/core/skills/gstack-harness/scripts/send_delegation_report.py \
  --project <PROJECT> \
  --lane planning \
  --task-id <TASK_ID> \
  --report-status done \
  --decision-hint proceed \
  --user-gate none \
  --next-action consume_closeout \
  --summary '<ONE_LINE_SUMMARY>'
```

This emits `OC_DELEGATION_REPORT_V1` through `lark-cli --as user`, which
`koder` can safely parse without depending on sender identity.

## Planner -> frontstage closeout

```bash
python3 <repo-root>/core/skills/gstack-harness/scripts/complete_handoff.py \
  --profile <project-profile.toml> \
  --source planner \
  --target koder \
  --task-id <TASK_ID> \
  --title '<TITLE>' \
  --summary '<CHAIN_SUMMARY>' \
  --frontstage-disposition AUTO_ADVANCE \
  --user-summary '<SHORT_USER_SUMMARY>'
```

If the user really must decide, use:

- `--frontstage-disposition USER_DECISION_NEEDED`
- `--next-action '<DECISION_QUESTION>'`

## Recovery playbook

If someone hand-wrote task state and a handoff drifted:

1. ensure the target `TODO.md` includes `task_id`, `source`, and `reply_to`
2. ensure there is a root seat `DELIVERY.md`, not only a task-local scratch file
3. ensure the target seat was notified through the standard transport
4. backfill the machine-readable receipt with the matching helper
