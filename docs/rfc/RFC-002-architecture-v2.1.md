# RFC-002 — ClawSeat Architecture v2.1

> **Status**: Draft (2026-04-26, by machine-memory)
> **Supersedes/Extends**: RFC-001 §1-§3（保留 v2 self-contained project 设计；本 RFC 加 L1-L3 分层 + decision escalation + privacy KB + koder 职责）
> **Owner**: machine-memory（架构）+ project-memory team（实施）
> **Operator approval**: 2026-04-26

---

## §0. 设计原则（来自 operator）

1. **架构优雅** — 一条规则覆盖一类问题，不堆特例
2. **逻辑鲁棒** — 每个边界明确，不靠默契
3. **易维护** — SSOT 单文件，多处引用 1 处真源
4. **命名简短** — role + scope-qualifier 两词足够，不引入新词
5. **职责单一** — 每个 seat 一个目的，不混淆

---

## §1. 命名（SSOT）

```
角色 (role):     memory  /  planner  /  builder  /  designer  /  koder
scope qualifier: machine-{role}   或   {project}-{role}
```

- 全仓 lowercase 英文，禁止 `ancestor` / `始祖`（除冻结 RFC-001 历史文档）
- skill / brief / commit / chat 全部用 `memory`
- v1 vocab `ancestor` 在批次 3 已部分清理（commit cf5282f / e2a0f5f / 1c1876c），剩余 deprecation pass 进 batch 4

---

## §2. 三层架构

```
L1: Operator (human)
        ↑↓ Feishu (decision card 双向翻译) | tmux/CLI 直连
    koder (1 per Feishu group, OpenClaw lark plugin, 0 state)
        ↑↓ tmux-send / agent-prompt
L2: machine-memory (1 per machine; claude opus 4.7; 战略层)
        ↕ memory↔memory cross-project (peer)
L3: <project>-memory (1 per project; codex gpt-5.4-mini default; 战术层)
        ↓ dispatch_payload
    <project>-planner (claude OR codex per template)
        ↓ dispatch
    <project>-{builder, designer} (codex / gemini per template)

强制 KB:
    ~/.agents/memory/machine/privacy.md (所有 seat pre-action 必读)
```

### §2.1 L2 machine-memory

- **数量**: 1 per machine
- **当前实例**: 我（外架，claude desktop）— 后续可能迁到 tmux session `machine-memory`
- **模型**: claude opus 4.7（重推理）
- **职责**: RFC / 跨项目仲裁 / OSS 发布 / 战略 / 当 project-memory 升级时介入
- **不做**: 项目内部 dispatch / backlog / STATUS 维护

### §2.2 L3 project-memory

- **数量**: 1 per project
- **当前实例**: install-memory (claude opus，待迁) + arena-memory (claude opus，待迁)
- **模型默认**: codex gpt-5.4-mini（轻量）
- **可 override**: install.sh `--memory-tool claude --memory-model claude-opus-4-7`
- **职责**: 项目 backlog / STATUS / dispatch / ack / cross-project tmux-send / 升级 Feishu
- **不做**: 业务代码 / 代码 review / 视觉 review / iTerm UI 配置

### §2.3 koder（侧边链）

- **数量**: 1 per Feishu group（不是 1 per project）
- **介质**: OpenClaw lark plugin（已实现 decision card UI）
- **状态**: 零状态（无 state 持久化）
- **唯一职责**: 双向翻译（详 §6）
- **不做**: 决策 / 业务回答 / 状态保存

---

## §3. 拓扑规则（一条覆盖全局）

> **每个 seat 只跟：同层 peer + 直接上下游通信。不跨层、不跨项目（除 memory↔memory）。**

允许的边:

| 边 | 用途 |
|----|------|
| operator ↔ koder | Feishu 用户接入 |
| operator ↔ machine-memory | tmux/CLI 战略对话 |
| machine-memory ↔ \<project\>-memory | 跨 scope 上下游 |
| \<project-A\>-memory ↔ \<project-B\>-memory | 跨项目 peer (tmux-send) |
| \<project\>-memory ↔ \<project\>-planner | 项目内上下游 |
| \<project\>-planner ↔ \<project\>-{builder,designer} | 项目内 dispatch |
| \<project\>-memory ↔ koder | 升级 Feishu / 接收用户翻译后指令 |

禁止的边:

- worker 跨项目通信（builder 不能跟另一项目的 builder 直发）
- machine-memory ↔ \<project\>-planner（必须经 project-memory）
- machine-memory ↔ worker（必须经 2 层）
- koder ↔ planner / worker（koder 只跟 memory + operator）
- planner ↔ planner 跨项目（项目自闭环）

---

## §4. 决策升级链

```
planner 遇决策点 → 通知 <project>-memory (decision_payload)
<project>-memory 触发 §5 判据，三选一:
  ├── 自决: 不在 §5 触发清单 → 直接 reply planner
  ├── peer 协商: 跨项目影响 → tmux-send <other>-memory，协商后 reply
  └── 升级 Feishu: §5 触发 → push koder
                      ↓
                  koder 读 supporting_docs + project STATUS
                      ↓
                  koder render decision card → Feishu group
                      ↓
                  operator 点按钮 OR 文字回复
                      ↓
                  koder 翻译为 agent-friendly prompt
                      ↓
                  <project>-memory 收 → reply planner
```

---

## §5. 升级 Feishu 的判据（强制）

`<project>-memory` 遇以下 6 类**必须**升级 Feishu，不许自决：

| 类别 | 触发例子 |
|------|----------|
| **breaking** | schema / API / config 不兼容改动；template 结构变更 |
| **secret** | OAuth login / API key 写入 / .env 修改 |
| **merge** | git merge to main / git push / release tag |
| **skill/RFC** | core/skills/* 或 docs/rfc/* 文件改动 |
| **preference** | 模型选择 / 模板选择 / 命名取舍 / 分工边界 |
| **scope dispute** | objective 模糊；跟现有 backlog 冲突；新 issue 无 precedent |

**6 类之外** = `<project>-memory` 自决（不许询问 operator）。

---

## §6. decision_payload 通信契约

跨 seat 决策传递的统一 schema（详 `core/schemas/decision-payload.schema.json`）:

```json
{
  "decision_id": "uuid-v4",
  "from_seat": "<project>-planner",
  "to_seat": "<project>-memory",
  "issue_id": "#N | NEW",
  "severity": "BLOCKER | HIGH | MEDIUM | LOW",
  "category": "breaking | secret | merge | skill | preference | scope",
  "context": "≤200 字问题陈述",
  "options": [
    {"id": "A", "label": "短描述", "impact": "一行后果"},
    {"id": "B", "label": "...", "impact": "..."}
  ],
  "default_if_timeout": "A | wait | abort",
  "timeout_minutes": 60,
  "supporting_docs": ["~/.agents/tasks/<project>/STATUS.md", "..."],
  "created_at": "ISO 8601"
}
```

**适用范围**:
- planner → memory（升级）
- memory → koder（Feishu 渲染输入）
- koder → memory（用户回复 + decision_id 关联回原决策）

---

## §7. koder I/O 协议

### OUTBOUND (agent → user)

- **输入**: `decision_payload` + `supporting_docs[]` 文件全文
- **处理**: 翻译成**通俗易懂、超高可读性**中文
- **输出**: Feishu interactive card
  - 标题 = 1 句话问题
  - 正文 = 背景 ≤ 100 字
  - 按钮组 = `options[].label` 一一对应
  - 兜底"我有别的想法"按钮 → 触发文字流程

### INBOUND (user → agent)

- **输入**: Feishu 按钮 click / 文字回复
- **处理**: 翻译成 agent-friendly prompt（含 `decision_id` 反查）
- **输出**: tmux-send 给 `<project>-memory`

### 约束

- 永不答业务问题（"为什么慢" → "已转 memory，请稍候"）
- 永不存状态（无 STATUS.md，无 backlog）
- timeout → 触发 `default_if_timeout`，不再问 memory

---

## §8. 责权（一句话）

> **每个 memory 全权拥有自己 scope 的 backlog/STATUS/dispatch。operator 可随时 override。**

- 不分 HIGH/MEDIUM 关闭权限
- 不要事前 OK
- 事后 operator 觉得不对就 reopen / 推翻

---

## §9. 隐私 KB（强制 pre-action 必读）

- **路径**: `~/.agents/memory/machine/privacy.md`
- **机器级**: 1 文件，所有项目所有 seat 共享
- **内容**: 不可 commit / 不可广播 / 不可 publish 的清单
  - 具体 key 名 / project 名 / customer 信息 / endpoint / token 模式
- **强制**: 任何 seat 在 commit / Feishu broadcast / 外部 publish 前**必须** read
- **违反**: hard fail，不许 override
- **载体**: skill `clawseat-privacy` 强制注入到所有 seat

---

## §10. 定时运维 (per-project patrol)

- **launchd plist**: `~/Library/LaunchAgents/clawseat.<project>-memory.patrol.plist`
- **触发**: 每天 03:00（per project）
- **动作**:
  1. STATUS.md 截断 dispatch log 至 last 20
  2. learnings/*.md 按 mtime 归档（>30 天移 archive/）
  3. MEMORY.md 索引重生成
  4. 把今日新 user feedback 同步到 `~/.claude/projects/.../memory/feedback_*.md`
  5. backlog 自动 close PASS commit 已 land 的 issue
- **生命周期**: install 时注册 plist + projects.json；unregister 时删 plist
- **不重蹈**: 跟 v1 clawseat-patrol 不同，per-project binding 严格，session name 用 v2 命名

---

## §11. 落地 milestones

### M1.6 (immediate batch 4)
- install.sh 改默认 memory 用 codex gpt-5.4-mini
- 建立 4 个新 skill：`clawseat-memory` / `clawseat-koder` / `clawseat-privacy` / `clawseat-decision-escalation`
- 写 `decision-payload.schema.json`
- backlog #15.b 完整清完 ancestor → memory rename

### M2 (1-2 周后, arena workload 数据驱动)
- per-project patrol plist 实施
- privacy.md starter 文档
- decision_payload 协议落地（planner / memory / koder 三方都 implement）
- watchdog cluster (#8) 选 2 个最痛的先做（tmux-health + iterm-grid）

### M3
- agentmemory MCP 集成（可选）
- OSS release: clawseat-memory-reporting + clawseat-decision-escalation skills

### M4
- v1 全清: 删 machine-memory-claude tmux session + PROJECT_BINDING.toml deprecation 完成

---

## §12. 跟 RFC-001 的关系

- RFC-001 §1-§3（v2 self-contained project / 始祖 = SEAT / workers + memories 双窗）**继续生效**
- RFC-001 §4-§6 milestones 被本 RFC §11 替代
- 本 RFC 是 RFC-001 的**架构精化**，不是 superseder
- vocab 上：本 RFC 钉死"memory"，RFC-001 的"始祖/ancestor"留作历史名词解释

---

*维护人*: machine-memory（=outer-architect）。每次架构层面演进 append 新 §或新 RFC，不就地修改本文件 §1-§11。
