---
name: clawseat-decision-escalation
description: >
  Decision escalation gate for ClawSeat situations blocked by automation or
  missing operator authority. Use when a workflow needs a user decision, when
  privacy or Feishu routing requires explicit approval, or when the correct
  next action has multiple viable choices. Also use when preparing three-option
  decision payloads for memory/operator review. Covers option framing,
  blocking-context capture, and safe escalation. Do NOT use for routine
  dispatch, code implementation, autonomous planning, or direct Feishu delivery
  without memory authority.
version: "1.0"
status: draft
author: machine-memory
review_owner: operator
spec_documents:
  - core/schemas/decision-payload.schema.json
  - docs/rfc/RFC-002-architecture-v2.1.md
related_skills:
  - clawseat-memory (project-memory 的实施载体)
  - clawseat-koder (Feishu 双向翻译载体)
  - clawseat-memory-reporting (chat 尾块格式 + STATUS dispatch log)
---

# clawseat-decision-escalation (v1)

> **what**: planner / memory / koder 之间传递决策的协议，涵盖判据、payload schema、升级路径、超时处理。
> **why**: 没有显式协议时，每个 seat 凭印象决定"问 operator 还是自决"，造成两种 anti-pattern：(1) 鸡毛蒜皮事打扰 operator，(2) 重大变更悄悄做完 operator 才知道。
> **how**: 6 类强制升级判据 + 单一 payload schema + 4 步升级链。

---

## 1. 三选一决策模型

`<project>-memory` 收到 `<project>-planner` 升级（或自己 patrol 时发现需决策）时，按下表选路径：

| 路径 | 触发条件 | 接下来 |
|------|---------|--------|
| **自决** | category **不在** §3 强制升级 6 类 | 直接 reply planner，dispatch 继续 |
| **peer 协商** | 跨项目影响（如改公共 skill）| tmux-send `<other>-memory`，协商达成共识后 reply planner |
| **升级 Feishu** | category **在** §3 6 类之一 | push koder → operator → 翻译回来 |

**关键**: §3 是**强制清单**，不是建议。memory **不许**在 §3 类别下自决。

---

## 2. 完整决策链

```
planner 遇决策点
   ↓ 写 decision_payload (schema in core/schemas/decision-payload.schema.json)
   ↓ tmux-send <project>-memory + 携带 payload JSON
<project>-memory 触发判据 → 三选一
   │
   ├── 自决: 不在 §3 → reply planner with chosen_option_id
   │
   ├── peer: 跨项目 → tmux-send <other>-memory，得 ACK 后 reply planner
   │
   └── 升级 Feishu: 在 §3
         ↓ tmux-send koder + payload + supporting_docs[] paths
         ↓
       koder 读 docs → render Feishu card
         ↓
       operator 点按钮 (chosen_option_id) OR 文字 (free_text_reply)
         ↓
       koder 翻译 → tmux-send memory + 完整 payload + decided_by + decided_at
         ↓
       memory reply planner
```

---

## 3. 强制升级 6 类（§3 / RFC-002 §5）

| 类别 | 触发例子 |
|------|----------|
| **breaking** | schema / API / config 不兼容改动；template 结构变更；删除已发布字段 |
| **secret** | OAuth login / API key 写入或修改；.env 任何动作；token 轮换 |
| **merge** | git merge to main / git push remote / release tag |
| **skill/RFC** | core/skills/* 或 docs/rfc/* 文件改动 |
| **preference** | model 选择 / 模板选择 / 命名取舍 / 分工边界 |
| **scope dispute** | objective 模糊 / 跟现有 backlog 冲突 / 新 issue 无 precedent |

不在以上 6 类 = `<project>-memory` 自决（**不许**询问 operator，不许升级）。

---

## 4. decision_payload 字段说明（详 schema）

最小必填字段:

```json
{
  "decision_id": "uuid-v4",
  "from_seat": "install-planner",
  "to_seat": "install-memory",
  "severity": "HIGH",
  "category": "preference",
  "context": "问题陈述 ≤200 字",
  "options": [
    {"id": "A", "label": "选项A 短描述", "impact": "选 A 的后果"},
    {"id": "B", "label": "选项B 短描述", "impact": "选 B 的后果"}
  ],
  "default_if_timeout": "A",
  "timeout_minutes": 60,
  "created_at": "2026-04-26T18:30:00+08:00"
}
```

可选: `issue_id`, `supporting_docs[]`

完成后 koder / memory 回填: `decided_at`, `decided_by`, `chosen_option_id`, `free_text_reply`

---

## 5. 超时处理

每个 payload 必须带 `default_if_timeout` + `timeout_minutes`。

`default_if_timeout` 的值:
- `"A"` / `"B"` / ... → 选定该 option，自动 dispatch
- `"wait"` → 延长 60 min 再轮一次（最多 3 轮，超过转 abort）
- `"abort"` → 取消决策，回 planner "decision aborted by timeout"

koder 监控 timeout_minutes 到期后**主动**触发 default 路径，不需要 memory 介入。

---

## 6. peer 协商（跨项目）

**触发**: memory 发现决策影响其他项目（如改 shared skill / vocab refresh / privacy.md）。

**协议**:
1. memory-A 写 payload，category="scope"，supporting_docs 包含相关共享文件
2. tmux-send `<other>-memory` payload
3. memory-B 在自己 backlog 里建 follow-up issue，回 ACK
4. memory-A 等所有 peer ACK 后，reply planner

**禁止**: peer 协商时跳过 §3 升级判据。如果 category 在 §3 里，必须**同时**升级 Feishu，不只 peer 协商。

---

## 7. 实施清单

| seat | 实施 |
|------|------|
| **<project>-planner** | 遇决策点写 payload + tmux-send memory；不直跳 koder / operator |
| **<project>-memory** | 收 payload → 判 §3 → 三选一；自决时也要在 STATUS.md dispatch log 标 `decided locally` |
| **koder** | 读 payload + supporting_docs → render Feishu card；用户回复后翻译 → tmux-send memory |
| **machine-memory** | 不在常规链路；只在 `<project>-memory` 升级到自己时介入（meta-architecture 决策）|

---

## 8. 反模式

| 反模式 | 后果 | 替代 |
|--------|------|------|
| planner 直接 ping operator (Feishu / chat) | 绕 memory，破坏 §3 判据 | 永远经 memory |
| memory 在 secret 类别下自决 | 违反 §3 | 必升级 Feishu |
| koder 答业务问题（"为什么慢"）| 越权决策 | "已转 memory，请稍候" |
| 不写 decision_id | 无法关联回复 | 每个 payload 必带 uuid |
| timeout 被忽略，operator 永远 block | 项目卡死 | koder 必须实现 timeout watchdog |

---

## 9. 验收

- planner 升级时写完整 payload（schema 校验通过）
- memory 自决时在 STATUS.md dispatch log 显式标 `decided locally (category=X)`
- memory 升级 Feishu 时 koder 在 ≤30s 内 render decision card
- timeout 到期 default 自动触发，operator 不在线不卡链
- decision_id 全程关联，操作员复盘时可 grep 出整条链
