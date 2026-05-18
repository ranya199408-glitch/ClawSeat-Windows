# Seat ownership matrix

Canonical writing boundaries for the install project.

## Per-seat ownership

| Seat | Owns / can edit directly |
| --- | --- |
| memory | own KB (orphan: decision/finding/task/plan), STATUS.md, TASKS.md, briefs/workflows it authors, MEMORY.md auto-memory |
| planner | design artifacts (briefs, workflows, contract drafts), planner KB |
| builder | repo code/tests/configs/SKILL.md/templates - sole repo committer |
| reviewer | review verdicts, finding/risk reports, reviewer KB |
| patrol | chain monitoring, drift detection, patrol KB |

## Single-owner rule

Each file has exactly one writing seat. Cross-seat reads are encouraged
(federated KB synthesis); cross-seat writes go through brief.

## Memory prose-only exception

See [core/skills/memory-oracle/SKILL.md](../skills/memory-oracle/SKILL.md)
for the prose-only exception rules.

## Planner /clear before dispatch

See [core/skills/planner/SKILL.md](../skills/planner/SKILL.md) for the
three-gate /clear-before-dispatch protocol.
