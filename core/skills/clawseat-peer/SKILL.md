---
name: clawseat-peer
description: >
  External peer protocol for non-canonical tmux workers. Use when a task is
  handled by a peer outside the project seat roster and needs durable peer
  deliveries, heartbeat tracking, or MiniMax readiness checks. Do not use for
  canonical seat dispatch, complete_handoff.py, or seat lifecycle changes.
---

# ClawSeat Peer

A peer is a non-canonical worker. It is not a seat and it never enters the
canonical dispatch/closeout chain.

## Identity
- `peer_id`: stable directory key for the external worker.
- `project`: owning install project.
- `peer-deliveries`: project-scoped under
  `~/.agents/tasks/<project>/peer-deliveries/<peer-id>/`.

## Directory Convention
- `meta.json`: peer identity, project, launched_at, status.
- `heartbeat.json`: latest peer heartbeat or activity timestamp.
- `tasks/<task_id>/TASK.md`: source brief or received task text.
- `tasks/<task_id>/DELIVERY.md`: final peer delivery with frontmatter.
- `tasks/<task_id>/receipt.json`: peer-facing ACK record, independent of
  canonical receipts.

## Boundary
- Memory may read peer `DELIVERY.md`, synthesize orphan KB, and ACK back in
  `receipt.json`.
- Do not call `dispatch_task.py` or `complete_handoff.py` for peer work.
- Do not treat a peer as a canonical seat or assume seat lifecycle ownership.

## Delivery Protocol
1. Peer updates `heartbeat.json` while working.
2. Peer writes `DELIVERY.md` with frontmatter `peer_id`, `task_id`, `status`,
   `summary`.
3. Peer writes `receipt.json` with `acknowledged_by`, `acknowledged_at`,
   `verdict`, `notes`.
4. Memory reads the delivery, writes orphan KB, and ACKs back in the peer
   receipt.
5. Peer stops on blocked scope and reports the blocker in the delivery
   summary.

## Helpers
- `scripts/peer_deliver.py`
- `scripts/peer_watchdog.py`
- `scripts/minimax_readiness.py`
