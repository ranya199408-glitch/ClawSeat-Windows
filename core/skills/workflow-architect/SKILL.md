---
name: workflow-architect
description: >
  Planner 专属 skill。接收 koder 传来的结构化用户需求 brief，将用户的真实操作步骤
  映射到系统原子能力（seats / tools / skills），设计出可执行的工作流规格（workflow spec），
  并将其沉淀为可复用模板。不做用户访谈（访谈由 koder 的 clawseat-intake 完成），
  不负责工具参数填充（参数由 designer 席位负责），只负责工作流「骨架设计」和「dispatch」。
planner-exclusive: true
---

# Workflow Architect
Writing boundaries: see [`core/references/seat-ownership.md`](../../references/seat-ownership.md).

## 职责边界

**做：**
- 读取 koder 传来的结构化 brief（来自 clawseat-intake 的 `summary_contract`）
- 将每个用户步骤映射到系统原子能力（seat / skill / tool）
- 输出符合 schema 的 workflow spec YAML
- 将 spec 沉淀为可复用模板（`reuse_goal: template` 时）
- 按 spec 中每个 step 的 executor 通过 gstack-harness dispatch_task.py 向下游派发

**不做：**
- 用户访谈（由 koder 的 `clawseat-intake` 完成）
- 工具参数填充（由 `designer` 席位负责）
- 实际执行任务（只负责骨架设计与 dispatch）

---

## 触发条件

激活本 skill，当：
- TODO.md 的 `task_type = workflow_design`
- 或 brief 中包含 **≥ 3 个跨席位步骤** 的操作流程

---

## 四阶段执行流程

### Phase 1 — 读 brief

从 TODO.md / DELIVERY.md 中提取以下字段：

| 字段 | 说明 |
|------|------|
| `workflow_steps` | 用户原始步骤列表（自然语言） |
| `reuse_goal` | `one-time`（单次执行）或 `template`（沉淀模板） |
| 约束条件 | 平台、时长、输出格式等限制 |

brief 格式来自 `clawseat-intake` 的 `summary_contract`。

### Phase 2 — 映射原子能力

直接对照项目内嵌的 seat / skill / tool 能力表完成映射。

将每个 `workflow_step` 映射到对应的 seat / skill / tool，并记录 executor 和 skill：
- 找到匹配能力 → 记录 `executor` 和 `skill`
- 无法映射 → 标记为 `UNKNOWN`，在 spec 的 `unknown_steps` 中注明「需用户决策」

### Phase 3 — 生成 workflow spec

生成 YAML spec 时确保包含 workflow_id、steps、reuse_goal、unknown_steps，并按内嵌 schema 组织字段。

输出 YAML spec，包含：
- `workflow_id`（slug 格式，如 `video-production-pipeline-v1`）
- `steps`（每步含 `executor`、`skill`、`inputs`、`outputs`）
- `reuse_goal`
- `unknown_steps`

当 `reuse_goal = template` 时，将 spec 写入：
```
~/.agents/tasks/{project}/workflows/{workflow_id}.yaml
```

### Phase 4 — 确认与 dispatch

1. 将 workflow spec 以可读格式展示（给 planner 自身确认，不面向用户）
2. 若有 `unknown_steps`，暂停并向 koder 澄清，再 dispatch 前等待确认
3. 按每个 step 的 `executor` 调用 dispatch_task.py 向对应席位派发

---

## gstack-harness 集成

**派发命令：**

```bash
python3 $CLAWSEAT_ROOT/core/skills/gstack-harness/scripts/dispatch_task.py \
  --profile <project_profile.toml> \
  --source planner \
  --target <executor> \
  --task-id {workflow_id}_{step_index} \
  --title "<step name>" \
  --task-type implementation \
  --objective "<step 详细说明>" \
  --test-policy UPDATE
```

每个 step 的 `task_id` 格式：`{workflow_id}_{step_index}`（如 `video-production-pipeline-v1_1`）

**进度与结果文件：**

result.json 和 progress.jsonl 格式遵循 `hierarchical-acp-delegation` 中的 ACP Progress File Protocol，不在此重复定义。引用该 skill 中的 schema 即可。

---

## 快速检查清单

在 dispatch 前自检：
- [ ] brief 中所有步骤都已映射（无遗漏 UNKNOWN，或 UNKNOWN 已经用户确认）
- [ ] workflow_id 为 slug 格式，不含空格
- [ ] `reuse_goal = template` 时 spec 文件已写入 workflows 目录
- [ ] 每个 step 的 task_id 唯一，格式为 `{workflow_id}_{step_index}`
- [ ] 使用 `--task-type implementation` 以便 review gate 正确路由
