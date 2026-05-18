---
name: clawseat-intake
description: >
  ClawSeat memory seat's intake clarification skill for tmux operator sessions.
  Use when an operator request is ambiguous, has multiple interpretations, spans
  multiple layers, or carries high cost or irreversible consequences. Ask one
  Socratic question per turn with 2-4 concrete options before executing. Also use
  when creative type, engineering scope, or required resources are unclear. Do NOT
  use for clear direct commands, quick diagnostics, or when the operator says "just do it".
---

# Clawseat-Intake

统一的 intake 路由器：判定意图 → 选方法论 → 澄清 → 输出可执行规格。

## 何时使用 / 何时跳过

**使用**:
- 请求模糊、关键信息缺失或存在多种解读
- 任务横跨多个层但边界不清
- 需要向下游 skill / ACP 委托链路交付稳定摘要
- 用户主动要求"先想清楚"

**跳过**:
- 需求已完整且无歧义
- 单文件小修改
- 用户明确说"直接做""just do it""别问了"

---

## Phase -1: 意图分类（新增）

用户开口后，先判定意图类型。不问用户"你想做创作还是工程"——从输入自动判定。

**创作信号**（任一命中 → 创作路径）：
- 提到具体创作物：视频、图片、音频、文案、剧本、PPT、分镜、角色设计
- 用了创作动词：做个、画个、写个、配个、生成
- `capability-catalog.yaml` 中非 `koder` / 非 `workflow-architect` 条目的 `triggers` 命中

**工程信号**（任一命中 → 工程路径）：
- 提到技术概念：功能、API、重构、bug、架构、数据库、部署
- 提到产品概念：我有个想法、brainstorm、值不值得做、新产品、方向
- `capability-catalog.yaml` 中 `koder` 或 `workflow-architect` 条目命中

**都不明确** → 问一个问题：
```text
你这次更想做哪类事情？

1. 创作类 — 视频、图片、音频、文案、设计
2. 工程/产品类 — 功能开发、架构、想法探索
```

**路由结果**：
- 创作 → Phase 0（能力匹配，走 catalog 收敛流程）
- 工程/产品 → Phase E0（工程诊断流程）
- 如果是"我有个想法/brainstorm/值不值得做" → 建议激活 `gstack-office-hours`，
  它有完整的 Startup/Builder 双模式诊断。本 skill 不替代 office-hours 的深度方法论，
  但提供轻量版工程诊断作为 fallback（见 Phase E0-E3）。

---

## 创作路径：Phase 0 → Phase 3

### Phase 0: 能力匹配

1. 读取 `references/capability-catalog.yaml`
2. 用 `triggers` 和 `user_examples` 匹配用户输入
3. 精确匹配唯一条目 → 直接锁定
4. 匹配多个条目 → 问用户选择
5. 无明确匹配 → 用最接近的 2-3 个做收敛式路由提问

如果条目存在 `template_index_path` → 进入 Phase 1。

### Phase 1: 模板匹配

仅对声明了 `template_index_path` 的 skill 生效。

1. 读取模板索引
2. 如果有条目，问：直接用现有模板 / 修改已有 / 新建
3. `existing` 或 `modify` → 直接输出摘要
4. `create` → 进入 Phase 2

### Phase 2: 需求澄清

根据匹配条目的 `required_fields` 动态生成问题。

规则：
- 每个问题来自 `required_fields[*].question`，选项来自 `options`
- 用户初始消息已回答的字段直接跳过
- 用户丢素材/链接/截图时，视为对相关字段的回答
- 用户催促"直接做" → 立即用当前信息进入 Phase 3
- 总问题数上限 7

**追问增强**（参考 office-hours 方法论）：
- 如果用户选了选项但附加说明含糊（"做个差不多的"），追问一次："差不多是指哪方面接近？风格？时长？还是内容结构？"
- 如果用户的回答自相矛盾（选了"快速出一版"但又要"长期复用"），指出矛盾并请用户取舍
- 不说"好的收到"——对每个回答给出一句判断："这意味着我们优先 X 而非 Y"

### Phase 3: 输出需求摘要

- 有 `summary_contract` → 按合同输出
- 无合同 → 通用摘要格式
- 输出后明确：这份摘要可直接作为下游执行规格

---

## 工程路径：Phase E0 → Phase E3（新增）

当用户的需求是工程/产品类时走这条路径。如果 `gstack-office-hours` 已安装且
用户的请求更像探索方向（"我有个想法""brainstorm"），建议用户激活 office-hours
获得完整的 Startup/Builder 诊断。以下流程作为轻量 fallback 和日常工程任务的
快速收敛。

### Phase E0: 问题定义

目标：把模糊的工程需求锐化为具体问题。

一次只问一个问题，**开放式追问**，不给选项卡：

1. **你要解决什么问题？** — 不接受功能描述，要问题描述。
   - 追问："谁在什么场景下遇到了什么困难？"
   - 如果回答是"我想加一个 XXX"，反问："加了之后解决谁的什么问题？"

2. **现在怎么凑合的？** — 现状是什么？用户/团队目前的 workaround 是什么？
   - 如果"没有 workaround"，追问："那这个问题真的够痛吗？"

3. **不做会怎样？** — 前提挑战。如果答案是"也没什么大事"，考虑建议不做。

**反谄媚规则**：
- 不说"不错的想法"——说"这个方向成立因为 X"或"这个方向有风险因为 Y"
- 不说"有几种方式"——选一个推荐并解释为什么
- 用户说的含糊词（"优化""改进""更好"）必须追问到具体指标

### Phase E1: 边界确认

目标：确定改动范围，防止 scope creep。

- **影响哪些模块/文件？** — 如果用户不确定，帮他推断但标注不确定性
- **什么算完成？** — 要具体到可验证的标准，不是"做好了就行"
- **什么不做？** — 明确排除项

### Phase E2: 方案对比（复杂任务必须）

当 Phase E0 判断任务复杂度为"多文件/跨模块"或更高时，必须提出至少 2 个方案：

```text
方案 A: <名称>
  做法: <1-2 句>
  优点: <2 条>
  风险: <1-2 条>
  工作量: S / M / L

方案 B: <名称>
  做法: <1-2 句>
  优点: <2 条>
  风险: <1-2 条>
  工作量: S / M / L

推荐: A，因为 <一句话理由>
```

### Phase E3: 输出任务规格

输出可直接 dispatch 给 planner 的任务规格：

```markdown
## 任务规格
**问题**: <一句话问题描述>
**目标**: <做什么，不是怎么做>
**验收标准**:
- <可验证条件 1>
- <可验证条件 2>
**不做**: <明确排除项>
**推荐方案**: <方案名称及要点>
**复杂度**: 单文件 | 多文件 | 多步骤工作流
**用户原始输入**: <原文>
```

---

## 提问格式

**创作路径**（Phase 0-3）：收敛式选项

```text
<一句话问题>

1. <选项> — <含义>
2. <选项> — <含义>
3. <选项> — <含义>
N. 其他（请描述）
```

**工程路径**（Phase E0-E3）：开放式追问

```text
<一句话问题>

（直接回答即可，不需要选数字）
```

每轮只推进一个问题。创作路径优先收敛选项；工程路径优先开放追问。

### Authority Boundary

- `clawseat-intake` 只负责诊断与澄清；Phase E0-E3 的输出是 advisory。
- 如果接下来需要的是 workflow spec、dispatch brief，或任何要写进 `workflow.md` 的规范，必须由 planner 派单给 `workflow-architect`。
- 不要把 intake 的结论当成 workflow authoring 的授权边界；它只提供问题定义和约束，不直接生成派工规范。

---

## 飞书通道适配

当可用飞书提问工具时：
- Phase 1 模板匹配使用卡片
- Phase 2 从 `required_fields` 动态生成卡片
- Phase E0 的开放式问题用普通文本消息
- 每次只推进一个字段

## 接收 memory 通知协议(BJ2)

memory 通过 lark-cli `--as user` 推飞书时，用 user 身份发送；人眼区分靠 prefix + footer。格式见 `core/references/feishu-message-marker.md`：

```markdown
[Memory]
{body markdown}

---
_via Memory @ {UTC ISO8601 timestamp} | project={p} | session={s} | task_id={id} | verdict={PASS|FAIL|BLOCKED}_
```

koder agent 收到时：

1. 识别 source：消息开头匹配 `^\[Memory\]` 即 memory 推送，不是真 user 输入。
2. Parse footer：提取 timestamp / project / session / task_id / verdict。
3. Format reply：把 body 转成飞书 markdown 卡片，遵循 `tui_card_format_draft.md`。
4. Auto-reply：见 BJ3；符合时用 lark-cli `--as user` 推回原 chat。
5. Privacy guard：reply 前按 clawseat-privacy 规则 grep PII / secret。

## Auto-reply 判断规则(BJ3)

收 memory `[Memory]` 通知后，自动回复必须同时满足：

- `verdict=PASS`
- body 不含 PII / secret / 内部 path，privacy guard PASS
- task_id 已知，memory KB 内有 record，非陌生来源
- chat_id 在 openclaw.json `allowed_groups` 白名单

任一条件不满足则不自动回复：`verdict=BLOCKED|FAIL` 留 user 手工介入；敏感内容改为“任务已完成,详情请联系 operator”；陌生 task_id 拒绝；chat_id 不在白名单则跳过。

---

## 行为规则

- **catalog 驱动**：创作路径的匹配、字段、摘要合同都从 `capability-catalog.yaml` 读取
- **模板优先**：有模板索引的 skill 先做模板匹配
- **术语翻译**：用户只看到业务语义，不看到技术词
- **行为即回答**：用户丢素材/示例时，视为回答
- **用户管是什么，Agent 管怎么做**
- **容忍覆盖**：用户随时改主意
- **不收素材**：素材收集属于下游 skill
- **先问后查**：摘要完成前，禁止读代码、提方案、改文件
- **与 ACP 委托衔接**：摘要/任务规格可直接用于 dispatch

**反谄媚规则**（创作和工程都适用）：
- 对每个回答给判断，不说"好的收到"
- 发现矛盾要指出
- 含糊词必须追问
- 不说"That's interesting" — 说"这有效因为 X"或"这有风险因为 Y"

---

## UX / Language Layer

User-facing wording follows:

- `references/shared-tone.md`：中文优先、低噪声、直接判断
- `references/i18n.md`：语言镜像和术语查询顺序
- `references/glossary-global.toml`：基础术语表，project glossary 可覆盖
- `references/capability-catalog.yaml`：创作/工程能力匹配与摘要合同
