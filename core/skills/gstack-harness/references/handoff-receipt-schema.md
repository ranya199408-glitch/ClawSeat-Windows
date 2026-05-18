# Handoff Receipt Schema

This reference documents the durable receipt shapes used by `dispatch_task.py`,
`complete_handoff.py`, `notify_seat.py`, and the planner strict fan-in checks.
The `.json.consumed` sentinel is a presence check, not a rich schema; the JSON
receipt is the canonical structured payload.

## 1. Dispatch receipt

Path pattern:

```text
<handoff_dir>/<task_id>__<source>__<target>.json
```

Required fields:

- `kind`: `"dispatch"`
- `task_id`
- `source`
- `target`
- `title`
- `test_policy`
- `todo_path`
- `reply_to`
- `assigned_at`

Optional fields:

- `correlation_id`
- `docs_consulted`
- `docs_skip_reason`
- `user_summary`
- `builder_commit`
- `memory_commit`
- `head_contains_commit`
- `lineage_status`
- `notified_at`
- `notify_message`
- `feishu_group_broadcast`
- `finding_id`
- `hypothesis_fix_counter`
- `hypothesis_fix_counter_exceeded`
- `rca_override`
- `core_ux`

## 2. Completion receipt

Path pattern:

```text
<handoff_dir>/<task_id>__<source>__<target>.json
```

Required fields:

- `kind`: `"completion"`
- `task_id`
- `source`
- `target`
- `branch_base`: git merge-base <feature_branch> <main>
- `branch_tip`: git rev-parse <feature_branch>
- `pr_number`: PR number used for closeout
- `ci_conclusion`: success | failure | strict-diff | strict_diff_zero
- `status`
- `title`
- `summary`
- `correlation_id`

Common optional fields:

- `test_policy`
- `delivery_path`
- `delivered_at`
- `source_todo_path`
- `used_fallback_delivery`
- `verdict`
- `frontstage_disposition`
- `next_action`
- `todo_path`
- `assigned_at`
- `notify_skipped`
- `notified_at`
- `notify_message`
- `feishu_delegation_report`
- `feishu_group_broadcast`
- `branch`
- `commit`
- `sweep_count`
- `core_ux_gate`
- `base_drift_acknowledged`
- `drift_reason`

Optional fields:

- `expected_base_sha`: git rev-parse of `clawseat/main` or `origin/main` captured by `dispatch_task.py` at dispatch time

## 3. Lineage extension fields

Step 1 keeps the canonical lineage schema in the completion receipt JSON.
`DELIVERY.md` frontmatter is not the canonical store for these fields in this
step.

The lineage extension fields are:

- `user_summary`
- `builder_commit`
- `memory_commit` (optional)
- `head_contains_commit` (boolean)
- `lineage_status` (`in-lineage` | `divergent` | `unknown`)

Grandfather window:

- completion receipts with a timestamp before `2026-06-20T14:55:53+08:00`
  may omit the lineage extension fields
- those legacy receipts are accepted with a deprecation warning on stderr
- receipts at or after the cutoff must include the required lineage fields

## 4. Consumed ACK

The durable ACK trail has two pieces:

- TODO line format: `Consumed: <task_id> from <source> at <iso8601>`
- Fan-in sentinel: `*.json.consumed`

The sentinel only records presence. For field-level contract checks, use the
JSON receipt fields above.


## DF completion receipt additions
- `base_drift_acknowledged` - optional boolean completion receipt field for intentional current-main drift.
- `drift_reason` - optional JSON string capturing `drift_from`, `drift_to`, and `orthogonal_files_verified`.

## DF dispatch receipt additions
- `finding_id` - optional string identifying the finding/hypothesis bucket for a dispatch.
- `hypothesis_counter` - optional integer count of dispatch attempts recorded for that `finding_id`.
