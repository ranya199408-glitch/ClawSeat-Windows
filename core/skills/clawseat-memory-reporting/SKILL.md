---
name: clawseat-memory-reporting
description: >
  Reporting helper for recording ClawSeat dispatch and completion events into
  durable project status surfaces. Use when logging a new dispatch, a
  specialist delivery, a consumed ACK, or a STATUS.md registry update. Also use
  when a chain needs consistent chat tail blocks or auditable progress history.
  Covers event normalization, status registry maintenance, and delivery
  traceability. Do NOT use for deciding task ownership, writing implementation
  code, reviewing diffs, or replacing planner/memory authority.
version: "1.0"
status: draft
author: memory
review_owner: operator
spec_documents:
  - references/status-md-schema.md
related_skills:
  - clawseat-ancestor (v0.7) — Phase-A bootstrap，本 skill 接管 Phase-B reporting
  - gstack-harness — dispatch 基础设施
---

# clawseat-memory-reporting (v1)

> **what**: memory seat 对 operator 的汇报应该走的格式 / 介质 / 时机协议。
> **why**: v2 早期实证（2026-04-26）memory 给 operator 的 "汇报" 是 Claude Code TUI 的原生 conversation 流，混着工具调用块、internal thinking 状态、长 sed 脚本、dispatch receipt JSON——operator 要滚 80+ 行才能知道"现在啥状态"。
> **how**: 把汇报拆成 4 层（STATUS.md 持久 / chat 尾块短摘要 / backlog detail / dispatch 1 行收据），每层有明确介质 + 触发时机 + 内容预算。

---

## 1. 四层汇报模型

| 层 | 介质 | 频次 | 内容预算 | 谁读 |
|---|------|------|---------|------|
| **L1 STATUS.md** | `~/.agents/tasks/<project>/STATUS.md` | 状态变化时即时更新 | 整文件 ≤ 100 行 | operator `cat` / 跨会话 reload |
| **L2 chat 尾块** | memory chat 每次回 operator 的最后一段 | 每次 operator 来访都有 | ≤ 5 行结构化 | operator 当下扫一眼 |
| **L3 backlog detail** | `docs/rfc/M1-issues-backlog.md` 等专项文件 | 发现新 issue / 更新进度时 | issue 内容自定 | operator 复盘 + 派工 |
| **L4 dispatch 收据** | chat 内联 1 行 | 每次 dispatch_task.py 执行后 | 1 行 | operator 流水扫 |

**核心原则**: chat 是 ephemeral conversation，**不该承担状态汇报职责**。状态走 L1 持久；chat 只放摘要 (L2) + 收据 (L4)。

---

## 2. L1 STATUS.md 协议

### 2.1 路径

`${AGENT_HOME}/.agents/tasks/<project>/STATUS.md`

每个项目自己一份；memory seat 是**唯一写入者**（其他 seat 只读不写）。

### 2.2 更新时机（强制）

memory **必须**在以下事件发生时即时更新（≤ 30s 内）:

- Phase-A → Phase-B 切换
- 新 dispatch 派出
- dispatch 完成（任意 verdict: PASS/FAIL/PARTIAL）
- 新 issue append 到 backlog
- 重大 architecture decision（如新加批次）
- operator 给 memory 的明确指令转化为 todo

memory **不应**为以下事件更新 STATUS.md（噪音）:
- 自己跑的 grep/cat/ls 等只读探索
- 内部 thinking / 构思
- backlog 里某 issue 的 minor 文案微调

### 2.3 schema

详见 [references/status-md-schema.md](references/status-md-schema.md)。

8 个 section（顺序固定，缺失 section 显式标 `(none)`）:

```
# <project> — STATUS

> updated: <ISO 8601 ts> by memory  |  brief mtime: <ts>

## phase
<phase=ready since <ts> | phase=bootstrap | phase=blocked: <reason>>

## roster
<one line per seat: id, tool, auth, session, alive/dead>

## active dispatches
<dispatch_id → target_seat (todo: <path>) — sent <ts>>
or: (none)

## pending operator decisions
<bullet list of things memory needs operator to choose>
or: (none)

## recent issues (last 5)
<#N severity status oneline>

## current milestone
<M1 batch 1 / M1 batch 2 / ...>

## next checkpoint
<what memory expects to happen next + ETA>

## dispatch log (append-only, last 20)
<ts: memory dispatched <id> to <target>>
<ts: <target> ack <id> verdict=<v>>
```

---

## 3. L2 chat 尾块协议

### 3.1 触发条件（强制）

memory **每次** 给 operator 回的消息（无论长短）都必须以尾块结尾，**例外**:
- operator 明确说"短回"或"OK"/"是"等单字，memory 也回单字
- 纯指令性确认（"已记录" 1 行），尾块可省略

### 3.2 格式

```
═══ STATUS ═══
phase: <ready | bootstrap | blocked>  |  M1 batch X: <progress shorthand>
dispatches: <id → target> | (none)
issues: <total> total / <open> open <highlights>
next: <≤ 80 字描述下一动作>
═════════════
```

**例**:
```
═══ STATUS ═══
phase: ready  |  M1 batch 1: A/B/D [done], C [in-progress]
dispatches: pkg-c → planner
issues: 14 total / 2 open (#3 banner LOW, #6 covered by C)
next: 等 C → 启动 batch 2
═════════════
```

### 3.3 不允许在 chat 出现的内容（转 L1/L3）

- 完整的根因分析 5 步链 → 写 backlog issue
- 完整的 dispatch receipt JSON → L4 1 行
- sed/grep 命令的完整输出 → 不展示，只说 "扫到 X 个匹配，详见 V2-VOCAB-DRIFT-AUDIT.md"
- commit 完整 stat → 只展示 "commit <sha> -- <files changed>"

---

## 4. L3 backlog detail 协议

### 4.1 文件归属

| 文件 | 内容 | 写入者 |
|------|------|--------|
| `docs/rfc/M1-issues-backlog.md` | M1 阶段所有 issue + operator 实时反馈 | memory |
| `docs/rfc/V2-VOCAB-DRIFT-AUDIT.md` | v1→v2 词汇漂移总账 | memory |
| `docs/rfc/RFC-001-*.md` | 架构决议（不可变） | memory + operator approval |
| `docs/rfc/SESSION-HANDOFF-*.md` | 跨会话 reload 快照 | memory（压缩前） |

### 4.2 issue append 模板

```markdown
### #N <一句话标题> — <🔴BLOCKER|🟠HIGH|🟡MEDIUM|🟢LOW>

**症状**: <observable behavior>

**根因**: <explanation if known, or "调研中"; 含 file:line 引用>

**修复**: <code/doc change required>

**Owner**: <builder-codex | planner-claude | designer-gemini | memory>
**批次**: <批次 N | 待派>

---
```

### 4.3 issue 编号规则

- 自增；不复用已删 issue 编号
- 严重度可升降（每次升降在 issue 末加 `**Severity update <ts>**: ... reason ...`）
- 状态：未派 / 派 X 进行中 / fixed @ <commit> / verified

---

## 5. L4 dispatch 1 行收据

### 5.1 chat 内联格式

```
dispatched <pkg-id> → <target_seat> (todo: <relative_path>)
```

**例**: `dispatched pkg-c-batch1-memories-tabs → planner (todo: install/planner/TODO.md)`

### 5.2 不展示的内容

- 完整 receipt JSON（写 STATUS.md dispatch log + 留 file path 即可）
- TODO.md 完整内容（写之前已经在 chat 里讨论过 objective）
- target_seat 的 ack 时间戳（async event，进 STATUS.md dispatch log）

---

## 6. 通知 operator 的渠道选择

| 场景 | 渠道 | 原因 |
|------|------|------|
| operator 在 memory pane 活跃 | chat 直接回 | operator 看着 |
| operator 离开 pane / 跨项目 | osascript 系统通知 (英文，ASCII) | 屏幕弹窗醒目 |
| operator 不在终端 / 远程 | Feishu 推送（如果项目绑了 group） | 异步触达 |
| 跨项目沟通（M2+） | `tmux-send <other>-memory ...` 直接互发 | 项目间不经 operator |

**约束**: osascript 通知必须**英文 ASCII**（macOS 菜单粘贴限制，见 memory `feedback_msg_scripts_english_only`）；中文走 chat。

---

## 7. 反模式（明确禁止）

| 反模式 | 为什么禁 | 替代 |
|--------|---------|------|
| "我刚跑了 grep 扫到 60+ 个匹配，列表如下：[80 行]" | 噪音 / 滚屏 | 写 audit 文件，chat 只留 "扫到 N 个，详见 X.md" |
| "现在我要派 Package C，objective 如下：[60 行 markdown]" | objective 应在 dispatch_task --objective 里，不在 chat | dispatch 完了 1 行收据 |
| "let me think about this... actually... wait..." (Claude Code thinking 泄漏) | thinking 是 internal | 直接给结论 |
| 每次回都重复长状态（"我们之前讨论过 X，X 是 Y..."） | 重复 / 冗余 | 引用 STATUS.md 或 issue 号 |
| 用 emoji 装饰 chat（除 RFC 决议表） | 视觉噪音 | 用 ASCII 分隔符 + 表格 |

---

## 8. 实施 roadmap

| 阶段 | 动作 | Owner |
|------|------|------|
| 立即 | 本 skill 写完 + STATUS.md schema 落地 | memory |
| 本周 | memory 自我规训按本协议汇报 | memory |
| M1 batch 2 | 改 install.sh / agent_admin 写 STATUS.md 的接口（让派给 planner 的 dispatch 自动追加 dispatch log） | builder-codex |
| M2 | cross-project 通知协议补全（M2 多项目场景） | memory |

---

## 9. 验收标准

- operator 在任何时刻 `cat ~/.agents/tasks/install/STATUS.md` 能在 ≤ 30s 内知道"现在啥状态"
- memory chat 任意一次回复，operator 看尾块就知道 phase/dispatches/issues/next
- 新 issue 发现后 ≤ 5min 内出现在 backlog（不是只在 chat 提一句）
- dispatch 派出后 ≤ 30s STATUS.md dispatch log 多 1 行
