# Peer Protocol

This document explains when to use a peer and when to use a seat.

## Short Rule

- Use a seat for work that belongs to this project's canonical dispatch chain.
- Use a peer for work done by an external worker that needs its own durable
  delivery trail.
- If the task needs `complete_handoff.py`, it is a seat task.
- If the task needs `peer-deliveries/<peer-id>/`, it is a peer task.

## What a Peer Is

- A peer is a non-canonical worker.
- A peer is not a seat.
- A peer does not enter the normal planner -> specialist -> planner chain.
- A peer writes its own delivery files and heartbeat files.
- Memory reads the peer delivery and can turn it into orphan KB.

## What a Seat Is

- A seat is a project role defined in the project profile.
- A seat participates in dispatch, delivery, review, and closeout.
- A seat uses the canonical handoff files and the canonical notify path.
- A seat is the right choice for install code, docs, templates, and infra.

## When to Use a Peer

- The worker is outside the project roster.
- The work is happening in an external tmux worker.
- The result needs project-scoped peer-delivery files.
- The task needs a separate heartbeat and readiness trail.
- The work should be acknowledged by memory without entering canonical flow.

## When to Use a Seat

- The work belongs to this repository.
- The work needs planner dispatch and builder implementation.
- The work will end in `complete_handoff.py` and `send-and-verify.sh`.
- The work changes install automation, protocols, or docs.
- The work needs review or canonical task status updates.

## Peer File Layout

```text
~/.agents/tasks/<project>/peer-deliveries/<peer-id>/
  ├─ meta.json
  ├─ heartbeat.json
  └─ tasks/<task_id>/
      ├─ TASK.md
      ├─ DELIVERY.md
      └─ receipt.json
```

## Delivery Flow

1. The peer receives a task brief.
2. The peer updates heartbeat while it works.
3. The peer writes `DELIVERY.md` with frontmatter.
4. The peer writes `receipt.json` with ACK fields.
5. Memory reads the delivery.
6. Memory writes an orphan KB summary.
7. Memory ACKs back to the peer receipt.

## What to Put in the Brief

- `task_id`
- `project`
- `summary`
- `expected evidence`
- `owner of the next action`

Keep the brief short. The durable files carry the full record.

## What Not to Do

- Do not call `complete_handoff.py` for peer work.
- Do not send peer work through canonical task receipts.
- Do not treat a peer as if it were a seat from the roster.
- Do not hide product ownership inside install infrastructure text.
- Do not assume a peer can replace planner or memory authority.

## Practical Examples

- Use a seat when changing `core/skills/clawseat-peer/SKILL.md`.
- Use a peer when an external cartooner-front worker produces a product fix.
- Use a seat when editing install docs or automation.
- Use a peer when the evidence must stay in peer-deliveries before memory
  synthesizes it.

## Decision Check

- Is the worker in the project roster? If yes, use a seat.
- Is the worker external? If yes, use a peer.
- Does the task need canonical handoff receipts? If yes, use a seat.
- Does the task need peer-deliveries and a heartbeat? If yes, use a peer.
- Is ownership unclear? Stop and escalate.

## Related References

- [ClawSeat Peer Skill](../core/skills/clawseat-peer/SKILL.md)
- [Peer vs Seat Boundary](../core/skills/clawseat-peer/references/peer-vs-seat-boundary.md)
- [Canonical Flow](CANONICAL-FLOW.md)
- [Seat Ownership Matrix](../core/references/seat-ownership.md)

