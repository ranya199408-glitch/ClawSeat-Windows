---
name: cs-workflow
description: Workflow design and execution skill. DESIGN mode: collaborative dialogue to assemble a workflow from capability-catalog tools. EXECUTE mode: runs an existing workflow file step by step, dispatching seats and handling gates. Does not implement an execution engine — dispatch logic is the planner's responsibility.
---

# CS-Workflow — Workflow Design and Execution

**Design principle**: Two modes, same skill. DESIGN produces a reusable workflow file; EXECUTE drives an existing one. Neither mode implements business logic — they route to the correct cs-* skills and seat roles.

## MODE 1: DESIGN（协商式工作流设计）

### INPUT

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `mode` | `"design"` | ✓ | 固定值，区分模式 |
| `user_brief` | string / path | ✓ | 用户业务需求（自然语言） |
| `research_report` | path | optional | 前期调研报告（如 RESEARCH-HERMES-B.md），用于启发工具选择 |
| `capability_catalog_ref` | path | optional | capability-catalog.md 路径，默认 `{CLAWSEAT_ROOT}/core/skills/cs-workflow/capability-catalog.md` |
| `workflow_name` | string | ✓ | 工作流名称（用于生成文件名） |

### PROCESS（对话驱动）

```
1. 若有 research_report → 展示调研摘要（关键工具/设计启示）作参考
2. 理解 user_brief → 识别业务步骤序列
3. 逐步澄清每个步骤：
   - 从 capability-catalog 匹配候选工具（列 name/场景/输出）
   - 说明每个工具的适用场景
   - 用户选择工具 → 确认 step 定义（输入/输出/gate）
4. 所有 steps 确认后，生成 workflows/<name>.md
5. 写 design_log.md（决策记录：每步为何选择该工具）
```

### OUTPUT

| File | Description |
|------|-------------|
| `{CLAWSEAT_ROOT}/core/workflows/<name>.md` | 工作流定义文件 |
| `{CLAWSEAT_ROOT}/core/workflows/<name>-design_log.md` | 决策记录 |

---

## MODE 2: EXECUTE（运行已有工作流）

### INPUT

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `mode` | `"execute"` | ✓ | 固定值，区分模式 |
| `workflow_name` | string | ✓ | 工作流名称（对应 workflows/<name>.md） |
| `project_params` | dict | ✓ | 执行参数（`brief_path`, `output_dir` 等，按各 step 的 input 需求） |

### PROCESS

```
1. 读 core/workflows/<name>.md → 解析 STEPS 列表
2. 按步骤顺序依次执行：
   a. 检查 condition（若有）→ 跳过或执行
   b. 解析 input_from（语义引用上一步输出）
   c. 向对应 seat_role dispatch 该 step 的 skill
   d. 等待 complete_handoff 返回
   e. 若 gate=user-confirm → 推飞书等确认后继续
3. 聚合所有步骤结果 → 写 execution_log.md
```

### OUTPUT

| File | Description |
|------|-------------|
| `execution_log.md` | 执行日志（每步状态/时间/结果路径） |
| final deliverable | 最终产出路径（由最后一步的 output 决定） |

---

## 工作流定义文件格式（`core/workflows/<name>.md`）

```yaml
---
name: <workflow_name>
type: workflow
version: 1
description: "一句话描述"
template: clawseat-engineering | clawseat-solo | ...
---

## STEPS

- id: <step_id>
  skill: <skill_name>         # 引用 core/skills/<name>/SKILL.md
  seat_role: <role>            # template 中定义的 role（如 planner / builder）
  input:
    <param>: <value>           # 直接值
    <param>: <step_id>.<field> # 语义引用上一步输出（不是模板引擎）
  gate: user-confirm | none    # 可选门控（user-confirm → 推飞书等确认）
  condition: <step_id>.<field> == <value>  # 可选条件执行
```

### 示例：ship-feature 工作流

```yaml
---
name: ship-feature
type: workflow
version: 1
description: "Standard feature shipping flow: plan → build → review → patrol"
template: clawseat-engineering
---

## STEPS

- id: plan
  skill: planner
  seat_role: planner
  input:
    brief: project_params.brief_path

- id: build
  skill: builder
  seat_role: builder
  input:
    workflow_path: plan.workflow_path

- id: review
  skill: reviewer
  seat_role: reviewer
  input:
    delivery_path: build.delivery_path
  gate: user-confirm

- id: patrol
  skill: patrol
  seat_role: patrol
  input:
    target: review.approved_branch
  condition: review.verdict == "APPROVED"
```

---

## EXECUTION NOTES

- **工作流组合由 planner 负责**：cs-workflow skill 描述 WHAT（接口），EXECUTE 模式的 dispatch 逻辑由接收 seat 决定
- **input_from 是语义引用**：不是模板引擎，EXECUTE 时由 planner 解析语义并构造实际路径
- **gate=user-confirm** 时调用 `send_delegation_report.py --user-gate required`，等确认后继续
- **condition** 为可选条件执行，不满足则 skip 该 step

## 禁止事项

- 不实现执行引擎（不写 Python 解释器）
- 不硬编码工具列表（工具来自 capability-catalog.md）
- 不自行决定 dispatch 路由（由 planner 按 seat_role 查找）
