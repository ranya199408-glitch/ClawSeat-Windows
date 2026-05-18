# Peer vs Seat Boundary

This note defines the line between an external peer worker and a canonical
seat in ClawSeat.
It applies to the install project and to the cartooner / cartooner-front
product surface.

## Terms

- peer: a non-canonical worker outside the seat roster, tracked under
  `peer-deliveries/`.
- seat: a canonical project role launched from the project profile and wired
  into the dispatch / closeout chain.
- product lane: cartooner / cartooner-front source, features, assets, and
  product bugs.
- infra lane: install project scripts, workflows, docs, templates, and task
  tooling.

## Ownership Map

| Surface | Owns it | Peer role | Seat role |
| --- | --- | --- | --- |
| cartooner / cartooner-front product code | product team | may inspect and report findings | may coordinate, but does not own the code |
| install automation and infra | install project | may consume the contract, not change it | owns the implementation |
| peer-deliveries directory | install project | writes peer artifacts there | reads it for synthesis / ACK |
| canonical handoff receipts | canonical seat chain | must not write them | owns them |

## Product Lane

- Product code belongs to the cartooner / cartooner-front owners.
- A peer may work against product code only when the brief names that product
  workspace and the task is explicitly external.
- Install seats do not silently patch product code on behalf of the product
  team.
- Findings about product code should be written as evidence, not as infra
  changes.

## Infra Lane

- Install scripts, workflows, docs, and helper CLIs belong to the install
  project.
- Builder may edit infra files when the workflow assigns that scope.
- A peer may not rewrite the canonical dispatch chain or the seat lifecycle.
- Canonical helpers such as `dispatch_task.py` and `complete_handoff.py` stay
  in the seat chain.

## Peer Deliveries

- Peer evidence lives under `~/.agents/tasks/<project>/peer-deliveries/<peer-id>/`.
- The directory is project-scoped, not seat-scoped.
- `TASK.md` records what the peer received.
- `DELIVERY.md` records what the peer completed.
- `receipt.json` records peer-facing ACK state.
- `heartbeat.json` records liveness or recent activity.

## Boundary Rules

- Do not use a peer as if it were a canonical seat.
- Do not use canonical handoff receipts for peer work.
- Do not let install infra changes leak into product code ownership.
- Do not let product code bugs reframe install infra ownership.
- If a task crosses both lanes, split the evidence and keep the ownership
  record explicit.

## Mixed Cases

- Product bug with install fallout: report the product defect and the infra
  impact separately.
- Infra bug that blocks product work: fix the infra bug in install, then keep
  the product evidence attached to the peer delivery.
- Unclear ownership: stop and escalate instead of guessing.

## What This Does Not Mean

- It does not authorize peer launch.
- It does not change planner dispatch rules.
- It does not change seat lifecycle or the canonical closeout contract.
- It does not add a second memory system.

## Reviewer Checklist

- Is the affected code product-owned or install-owned?
- Is the worker a peer or a canonical seat?
- Is the evidence stored in the correct delivery path?
- Are we avoiding a hidden cross-lane write?
- Does the summary say who owns the next action?

