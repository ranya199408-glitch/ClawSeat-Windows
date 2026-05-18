# Canonical Flow (v0.7)

> Shortest 明确、最不容误解的 ClawSeat dispatch / completion / ACK 协议说明。
>
> **v0.7 范式**：operator ↔ memory 走 **CLI 直接交互**；飞书通道为**可选 write-only
> 广播** + 可选的 **koder 反向通道**（见 [INSTALL.md](INSTALL.md) §4）。本文件描述的
> dispatch / completion / ACK 协议在 CLI-only 和 Feishu-enabled 模式下**均适用**；
> 差异只在"是否经飞书转发"这一步。
>
> Seat lifecycle entry points are documented in
> [docs/ARCHITECTURE.md §3z](ARCHITECTURE.md#seat-lifecycle-entry-points-v07-pyramid).
> This file describes the dispatch / completion / ACK protocol *between
> already-launched seats*; it does not describe how to launch them.

---

## 1. Dispatch（前端 → 执行位）

```bash
python3 dispatch_task.py \
  --profile <profile> \
  --source <source_seat> \
  --target <target_seat> \
  --task-id <TASK_ID> \
  --title '<TITLE>' \
  --objective '<OBJECTIVE>' \
  --test-policy UPDATE \
  --reply-to <reply_to_seat>
```

**dispatch_task.py 自动完成：**
1. 写入 `TODO.md`（target 的 inbox）— 详见 [§9 TODO.md / DELIVERY.md 格式](#9-todomd--deliverymd-格式) 的 schema
2. 更新 `TASKS.md` / `STATUS.md`
3. 通过 tmux 通知 target seat（`send-and-verify.sh`，1 秒后 Enter）
4. 若配置了飞书群且 `CLAWSEAT_ENABLE_LEGACY_FEISHU_BROADCAST=1`，则向飞书群广播任务发布
5. 写入 machine-readable handoff receipt

> **飞书群广播默认关闭**。需显式设置 `CLAWSEAT_ENABLE_LEGACY_FEISHU_BROADCAST=1` 才启用。

---

## 2. Completion（执行位 → 前端）

```bash
python3 complete_handoff.py \
  --profile <profile> \
  --source <source_seat> \
  --target <target_seat> \
  --task-id <TASK_ID> \
  --title '<TITLE>' \
  --summary '<CHAIN_SUMMARY>' \
  --frontstage-disposition AUTO_ADVANCE \
  --user-summary '<SHORT_USER_SUMMARY>'
```

**complete_handoff.py 自动完成：**
1. 写入 `DELIVERY.md`（planner inbox）
2. 若配置了飞书群且 `CLAWSEAT_ENABLE_LEGACY_FEISHU_BROADCAST=1`，则向飞书群广播delegation report
3. 写入 machine-readable handoff receipt（`Consumed:` 待前端标记后写入）

> **Review gate**：如果任务会修改 docs / templates / skills / protocol / config / source code，planner 不应直接把它当成 review-free 的自闭环任务。默认先走 builder（如需实现），再由 planner 做代码审查，最后才允许 frontstage closeout。纯审查/调研任务只有在任务本身明确声明 review-free 时才可跳过 review lane。

---

## 3. OC_DELEGATION_REPORT_V1（可选的 Feishu-side control packet）

> v0.7 里 OC_DELEGATION_REPORT_V1 **不是**主通道，只在 **koder 反向通道已启用**
> （operator 从手机发消息，koder 负责解析并转发给 ClawSeat seat）时才会被生成。
> CLI-only 模式下 seat 之间走 tmux send-keys + handoff receipt，无需此信封。

当飞书通道启用时，planner → koder 通过 `lark-cli --as user` 发送结构化信封：

```
[OC_DELEGATION_REPORT_V1]
project=<project>
lane=<planning|builder|designer|frontstage>
task_id=<TASK_ID>
dispatch_nonce=<nonce>
report_status=<in_progress|done|needs_decision|blocked>
decision_hint=<hold|proceed|ask_user|retry|escalate|close>
user_gate=<none|optional|required>
next_action=<wait|consume_closeout|ask_user|retry_current_lane|surface_blocker|finalize_chain>
summary=<单行摘要>
[/OC_DELEGATION_REPORT_V1]
```

**koder 只需看四个字段即可判断行为：**

| report_status | decision_hint | user_gate | next_action | koder 行为 |
|---|---|---|---|---|
| `done` | `proceed` | `none` | `consume_closeout` | 自动推进 |
| `done` | `close` | `none` | `finalize_chain` | 收尾 chain |
| `needs_decision` | `ask_user` | `required` | `ask_user` | 问用户 |
| `blocked` | `retry` | `none` | `retry_current_lane` | 重试当前 lane |
| `blocked` | `escalate` | — | `surface_blocker` | 向用户呈现阻塞点 |

> **不需要依赖 sender 语义**。消息通过用户身份发送，planner lane 身份已在 `lane` 字段中标识。

**不依赖 sender 语义的协议规则：**
- `source=planner` 禁止出现在 envelope 中
- `lane` 字段标识执行 lane，不是发送者身份
- 所有字段均为结构化枚举，koder 可机器解析

---

## 4. Consumed ACK（ durable 收据）

specialist 完成任务后，planner 写入 `Consumed:` ACK 到 handoff receipt：
```json
{
  "task_id": "<TASK_ID>",
  "source": "<source>",
  "target": "<target>",
  "consumed_at": "<timestamp>",
  "status": "consumed"
}
```

---

## 5. 三 Artifact 缺一不可

planner closeout 回 frontstage 必须同时有：
1. `DELIVERY.md`（内容文档）
2. seat-to-seat notify（tmux 或飞书群通知）
3. machine-readable handoff receipt（`handoffs/` 下的 JSON）

---

## 6. 席位通知路径选择（v0.7）

| 场景 | 通知路径 |
|------|---------|
| 默认（CLI-only）| `send-and-verify.sh` → tmux send-keys 直送目标 seat 的 tmux session（`<project>-<seat>`）|
| Koder overlay 已启用（optional）| 飞书群（`lark-cli --as user` via `send_delegation_report.py`）；operator 从手机发的指令走这条路 |
| Planner 主动广播 | Planner stop-hook → `lark-cli msg send` 结构化摘要到群（write-only，不解析回复）|

> **旧的"打开飞书群广播必须"已废弃**。v0.7 下 `CLAWSEAT_ENABLE_LEGACY_FEISHU_BROADCAST`
> 默认关闭；planner 的结构化广播是**新路径**，独立于旧的 delegation broadcast 开关。

---

## 7. Project-Group Bridge Binding（optional — only when Feishu enabled）

> v0.7 下该 bridge 是可选的：CLI-only 模式完全不需要。仅当已跑
> `scripts/apply-koder-overlay.sh` 并希望 operator 从飞书远程指挥时才需要绑定。

project ↔ Feishu group 的 durable bridge mapping 存储在：

`~/.agents/projects/<project>/BRIDGE.toml`

Schema:

```toml
[bridge]
project = "<project_name>"
group_id = "<feishu_group_id>"
account_id = "<koder_app_id>"
session_key = "<openclaw_session_key_or_prefix>"
bridge_mode = "user_identity"
bound_at = "<ISO8601_timestamp>"
bound_by = "<user_who_authorized>"
```

约束规则：

1. 一项目一群
2. 一群一项目
3. 禁止多个项目绑定到同一个群
4. 绑定操作必须带显式用户授权确认

OpenClaw bridge 操作方法：

- `bind_project_to_group(project, group_id, account_id, session_key, bound_by, authorized=True)`
- `list_project_bindings()`
- `get_binding_for_group(group_id)`
- `unbind_project(project)`

---

## 8. Configuration And Verification

安装完成并不意味着可以直接进入业务执行。canonical 主线应先进入配置阶段：

1. `configuration entry`
   - 选择当前项目 / 切换项目
   - 完成 Feishu `group_id` 绑定
   - 选择 tool / auth_mode / provider
   - 配置 API key / secret
   - 配置 base URL / endpoint URL

2. `configuration verification`
   - 验证 Feishu bridge 是否可用
   - 验证 API key 是否能完成最小调用
   - 验证 base URL / endpoint 是否可达
   - 验证 auth_mode / provider 是否与 seat 配置一致

planner 默认不负责明文 secret 录入，但应在配置变更具备连通性或回归风险时安排验证，尤其包括：

- Feishu bridge 配置
- 新 API key
- key rotation
- base URL / endpoint 修改
- auth_mode / provider 切换

配置阶段完成且验证通过后，才进入正常执行阶段。

---

## 9. TODO.md / DELIVERY.md 格式

`dispatch_task.py` / `complete_handoff.py` 写入的 inbox 文件有稳定契约，供 seat 读取与 patrol 扫描。对应 schema 实现在 `core/skills/gstack-harness/scripts/_task_io.py`。

**TODO.md（target seat 的 inbox，由 dispatch_task 写入）**：

```text
task_id: <task-id>
project: <project-name>
owner: <target-seat>
status: pending
title: <task title>

# Objective

<objective body as markdown>

# Dispatch

source: <source-seat>
reply_to: <reply-to-seat>
dispatched_at: <ISO-8601 UTC>
```

**DELIVERY.md（source seat 的 outbox，由 complete_handoff 写入）**：

```text
task_id: <task-id>
owner: <source-seat>
target: <target-seat>
status: completed
date: <ISO-8601 UTC>
correlation_id: <optional>

# Delivery: <title>

## Summary

<summary body>

Verdict: <pass|fail|defer|...>          # optional
FrontstageDisposition: <AUTO_ADVANCE|HOLD|ESCALATE>  # optional
UserSummary: <short user-facing line>   # optional
NextAction: <optional>
```

**Consumed ACK**（frontstage 消费 delivery 后追加到 DELIVERY.md 末尾）：

```text
Consumed: <task-id> from <source-seat> at <ISO-8601 UTC>
```

Queue 模式（`append_task_to_queue` 写入）在 owner 已有 `[pending]`/`[queued]` 任务时把新任务标记为 `[queued]`；首任务完成后自动晋升下一条到 `[pending]`，完成条目归档到 `# Completed` 段落。具体规则见 `_task_io.py::append_task_to_queue` / `complete_task_in_queue`。
