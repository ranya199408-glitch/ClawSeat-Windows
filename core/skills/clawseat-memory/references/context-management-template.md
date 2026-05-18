# Context Management Template

## Context Management

### [CLEAR-REQUESTED]

Output this marker as the last line when ALL of:

- step status -> done
- artifacts written to disk
- `clear_after_step: true` in workflow.md step

Stop hook will trigger external `/clear` on this marker.

### [COMPACT-REQUESTED]

Output this marker when:

- Context usage > 80% within a step
- `iter > 1` or post-subagent fan-out makes context heavy

Stop hook will trigger `/compact` on this marker.

If both markers could apply, finish durable writes first, then emit exactly one
marker as the final line.
