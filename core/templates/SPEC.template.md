---
spec_id: {{TASK_ID}}
project: {{PROJECT}}
version: 0.1
status: drafting
created_by: memory
created_at: {{TIMESTAMP}}
last_amended_at: {{TIMESTAMP}}
parent_task: null
---

# {{TITLE}}

> **状态**: 草稿中 (drafting) — memory 与 user 协商需求阶段，未锁定执行。
> **锁定后**: 任何变更必须走 `spec_admin.py amend` 流程，影响范围内的 specialist 收新 brief。

## 1. 目标（North Star）

<!-- 一句话讲清楚要做什么、为谁、为什么。 -->


## 2. 输入与前置条件

<!-- 当前代码/分支状态、依赖任务、用户已锁定的决策。 -->

- 当前分支：
- 依赖任务：
- 用户已锁定决策：


## 3. 交付物（Deliverables）

<!-- 具体文件路径 / API endpoint / UI 行为 / 命令产出。 -->

- [ ] `<file-or-symbol>`：<预期内容或行为>
- [ ] `<file-or-symbol>`：<预期内容或行为>


## 4. 验收准则（Acceptance Criteria）

<!--
每条准则带 ID（AC-N）、判定方式（assert: <shell-cmd> / script: <path> / 人工）、状态。
- assert: 单命令，exit 0 = 通过。
- script: 复杂检查放 acceptance/ 子目录。
- 人工：memory 推飞书让 user 看截图/对话。
准则必须可执行或可观察，不能写"代码组织合理"这种主观项。
-->

| ID | 准则 | 验证 | 状态 |
|----|------|------|------|
| AC-1 | <准则文字> | `assert: <shell-cmd>` | pending |
| AC-2 | <准则文字> | `script: acceptance/ac2-<slug>.sh` | pending |
| AC-3 | <准则文字> | 人工 | pending |


## 5. 反范围（Out-of-Scope）

<!-- 明文列出不做的事，防 scope creep。-->

- 不做：
- 不动：
- 不引入：


## 6. 约束

<!-- 用户能感知的约束。性能、安全、兼容、技术栈选型限制。-->

- 性能：
- 兼容性：
- 安全：
- 其它：


## 7. 引用的外部文档

<!-- 引用 sub-docs 进入 acceptance scope。未引用的 sub-docs 算背景资料，不算契约。-->

<!-- - DESIGN.md §X.Y（视觉规格） -->
<!-- - ARCH.md §A.B（架构决策） -->


## 8. 变更历史

<!-- 由 spec_admin.py amend 自动追加；不要手动改这一节。-->

| 版本 | 时间 | 变更摘要 | 触发人 |
|------|------|---------|--------|
| 0.1 | {{TIMESTAMP}} | 初版草稿 | memory |
