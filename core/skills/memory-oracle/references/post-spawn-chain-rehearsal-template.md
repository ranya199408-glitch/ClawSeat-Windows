# Post-Spawn Chain Rehearsal Brief Template

**Suggested task name**: `chain-rehearsal-<YYYYMMDD>-<project>`

**Brief text memory can reuse**:

> Task: protocol self-check rehearsal (self-introduce + four-step flow demo)
>
> Each specialist seat (planner / builder / designer / patrol / reviewer, as
> present in the project roster) must self-report in this format:
>
> ```text
> role: <read from SKILL.md / WORKSPACE_CONTRACT.toml>
> boundary:
>   - Do: <one sentence>
>   - Don't: <one sentence>
> closeout two-step: <what two actions complete an assigned task>
> fan-out trigger: <when this seat must fan out>
> relay chain: <who this seat notifies after completion>
> ```
>
> planner must split this brief into N workflow steps, one step per specialist,
> using `dispatch_task.py` to write `workflow.md` with `notify_on_done:
> [planner]`.
>
> Each specialist completes its self-report by calling `complete_handoff.py` to
> write the durable `.consumed` receipt, then calling `send-and-verify.sh` only
> to wake planner.
>
> planner fans in every specialist self-report, updates `planner/DELIVERY.md`
> with `verdict=PASS`, then uses `send-and-verify.sh` to relay to memory:
> `[chain-rehearsal-<ts>] all-seats-online — verdict PASS`.

**Memory verification checklist after planner relay**:

- `handoffs/` contains one `.consumed` receipt for every participating seat.
- `planner/DELIVERY.md` contains the fan-in summary and `verdict=PASS`.
- Each self-report matches the seat's current SKILL.md role, boundary,
  closeout two-step, fan-out trigger, and relay chain.

**Failure handling**:

Do not proceed to real task dispatch after a failed rehearsal. Fix the protocol
gap for the failing seat, then rerun the rehearsal until the chain passes.
