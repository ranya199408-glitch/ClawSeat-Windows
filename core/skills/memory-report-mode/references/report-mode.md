# Report Mode

Report mode runs when `sender == "planner"`. It translates planner-facing engineering language into a user-facing AUTO decision report.

## AUTO Decision Format

Use one line:

```text
[Action] [Reason 1 sentence]
```

No preamble, no "I recommend", and no approval question. Memory is acting on behalf of the user, so it reports the action and the reason.

Example:

```text
派工给 builder 实现 X（因为 Y 是当前优先级，Z 已完成）。
```

## Normal Report

Use an info card when the channel benefits from visual structure, but keep the content one decision wide:

```markdown
### ✅ 已处理

**动作**：派工给 builder 实现 X<br>
**理由**：Y 是当前优先级，Z 已完成。

*decision-log 已记录*
```

## Goal Drift Signal

If the planner message mentions or implies a goal drift signal, do not emit the normal AUTO line. Prompt the user for realignment with a recall card:

```markdown
### ⚠️ 我感觉到目标可能在偏移

**信号**：<具体漂移信号>
**我担心的**：<一句话说明风险>

---

回复数字：
1. 对，重新校准
2. 没事，继续
3. 详细解释
```

Goal drift recall is the only report-mode path that asks the user to choose.
