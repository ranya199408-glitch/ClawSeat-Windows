# Goal Drift Signals

Memory watches for four goal drift signals. A signal does not prove the project is wrong; it means user realignment is cheaper than silently continuing.

## 1. 范围蔓延

- Detection rule: a new requirement appears after scope lock, or implementation scope is materially larger than the accepted brief.
- Threshold: actual changed surface exceeds the original spec by more than 2x, or any new user-visible requirement lands after scope lock.
- User prompt: `这次新增的 <requirement> 已超过原范围。要重新校准目标，还是作为独立后续任务处理？`

## 2. 里程碑超期

- Detection rule: a blocked item consumes more time than the plan assumed.
- Threshold: more than 20% of estimated time has elapsed while the item is still blocked, or actual/estimated time exceeds 1.5x.
- User prompt: `<milestone> 已超过预期时间。要压缩范围、继续修阻塞，还是改下一个里程碑？`

## 3. 假设过时

- Detection rule: a dependency, default tool, branch state, external API, or policy changed after the last decision.
- Threshold: any changed assumption invalidates an accepted plan, test expectation, or dispatch route.
- User prompt: `之前的判断基于 <old_assumption>，现在变成 <new_assumption>。要按新前提重排吗？`

## 4. 焦点偏移

- Detection rule: current work no longer maps to the north-star goal or accepted milestone.
- Threshold: 3+ consecutive dispatches are unrelated to the north-star, or the last 24h of work does not advance the declared milestone.
- User prompt: `最近 3 个派工都不直接推进 <north_star>。这是有意转向，还是需要拉回主线？`

## Recall Behavior

Use a recall card with at most three options. Do not ask for approval on normal AUTO decisions; ask only when one of these signals crosses its threshold.
