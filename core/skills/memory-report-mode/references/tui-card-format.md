# TUI Card Format

Claude Code renders Markdown well enough for compact cards. Use cards for memory-facing user UX; Feishu uses native interactive cards.

## Common Shape

```markdown
### {emoji} {title}

**{field}**：{value}

**{field}**：
- {value 1}
- {value 2}

---

*{footnote}*
```

Do not use ASCII borders. They break in mixed Chinese/English output.

## 信息卡

Use an info card for status updates and AUTO decisions. No user action is needed.

```markdown
### ✅ 已处理

**任务**：T3 描述审核<br>
**结果**：通过

**理由**：
- 8 条描述都 < 150 字
- 意思都保留
- 符合 RFC-002

*decision-log 已记录*
```

## 召回卡

Use a recall card only when goal drift is detected and the user must decide whether to realign.

```markdown
### ⚠️ 我感觉到目标可能在偏移

**信号**：M1.6 已经 6 天了（最初预计 3-4 天），中间加了 2 个 micro-fix
**我担心的**：是不是又在"再修一个就好"循环里？

---

回复数字：
1. 对，方向偏了 — 重新校准
2. 没事，继续 — 这是预期内
3. 详细解释 — 给我更多信息
```

Numbered options appear only in recall cards. Limit options to three.

## 复盘卡

Use a reflection card for periodic summaries. It is read-only.

```markdown
### 🔄 复盘 — M1.6 完成

**这阶段做了什么**：
- 派发 4 个 sub-package
- 审核 8 条描述
- 解决 1 个 P1 micro-fix

**下阶段建议**：
- M2 决策更密集，复盘频率可以加密

*完整复盘见 reflection-history.md*
```

## Density

Use at most one main card per turn. If several AUTO decisions happen together, aggregate them into one list card instead of emitting several cards.
