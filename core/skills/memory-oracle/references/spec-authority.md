# Memory Spec Authority（v0.9 草案 — install dogfood）

Memory 是 **task spec 的唯一作者和验收方**。Spec 把任务的「done」客观化，消除 planner / reviewer / user 之间对"完成与否"的主观分歧，也是 rework 协议的契约基础。

## 何时写 spec

`clawseat-intake` 走完后，需求至少满足以下任一条件就 **MUST** 落 `SPEC.md`：

- 跨多个 seat 的协作链（builder + reviewer + 任何第三方）
- 用户预期里包含明确交付物清单或验收要点
- 任务可能要 rework（reviewer 可能给非 APPROVED verdict 的）

简单单 seat 一次性任务（例：「memory 重新跑一次 scan」）可以跳过。

## Spec 文件位置

```
~/.agents/memory/projects/<project>/spec/<task_id>/
├── SPEC.md                    ← 契约主文件（memory 拥有）
├── amendments/000N-<slug>.md  ← 变更历史（spec_admin amend 自动写）
└── acceptance/                ← 可选，复杂 AC 用的脚本
```

## 工具

```bash
python3 core/scripts/spec_admin.py create  --project <p> --task-id <id> --title "<t>"
python3 core/scripts/spec_admin.py lock    --project <p> --task-id <id>          # 草稿→锁定，进入执行阶段
python3 core/scripts/spec_admin.py amend   --project <p> --task-id <id> --summary "<change>" \
                                           --proposer user --approved-by user \
                                           --impact-mode queue|suspend|redirect
python3 core/scripts/spec_admin.py verify  --project <p> --task-id <id>          # 跑所有 AC assert / script
python3 core/scripts/spec_admin.py show    --project <p> --task-id <id>          # 状态 / AC 概览
python3 core/scripts/spec_admin.py close   --project <p> --task-id <id>          # 最终验收后归档
```

## Spec 生命周期（drafting → locked → amending → closed）

1. **drafting**：memory 与 user 协商。memory 草拟、user 反馈、memory 修订。锁定前可以无成本反复修改。
2. **locked**：memory 调 `lock` 后，spec 进入执行基线。`dispatch_task.py` 派工的 `expected_base_sha` / `expected_branch` 以此为锚。
3. **amending**：locked 状态下 user / planner 提议变更 → memory 走 amendment 流程，写入 amendments/ + 影响范围内 seat 收新 brief。
4. **closed**：planner 最终 relay 后 memory 跑 `verify`，全部 AC 通过且 user 确认后 `close`。

## Acceptance Criteria 写作纪律

| 验证方式 | 适用 | 例 |
|---------|------|----|
| `assert: <cmd>` inline | 单命令、exit 0 即通过 | `assert: pnpm typecheck` |
| `script: acceptance/<id>.sh` | 复杂逻辑、多命令 | 启动服务后 curl + jq 比对 |
| `人工` | 视觉 / 体感 / 难自动化 | memory 推飞书让 user 看截图 |

**纪律**：**每条 AC 写出来都要先问能不能写成 assert**。写不成 assert 的 AC 是设计气味 — 要么太主观（"代码组织合理"），要么实质是判断而非需求。

## Amendment 流程（user 中途修改 spec）

User 通过 chat / 飞书提议变更时：

1. memory 读现有 SPEC.md 评估影响范围（哪些 in-flight seat / 哪些已交付 deliverables 受影响）
2. memory 推飞书 / chat 卡片：`提议 SPEC v<X> → v<Y>: <change>`、影响清单、[确认] [取消] [继续讨论]
3. user 确认后，memory 调 `spec_admin.py amend ... --impact-mode <mode>`
4. memory 给受影响的 in-flight seat 重派工（impact_mode 决定语义）：

| impact_mode | 语义 | 何时用 |
|-------------|------|--------|
| `queue` | 当前 task 跑完再生效 | 加 AC / 加交付物 / 小调整 |
| `suspend` | 立即暂停当前 task，按新 spec 重启 | 删 AC / 缩 scope / 已交付违反新约束 |
| `redirect` | 当前 task 作废，按新 spec 完全重新派工 | 改目标 / 改方向 |

memory 在确认卡里给出推荐 mode，user 可覆盖。

## 最终验收（planner relay → memory acceptance gate）

planner 把 chain-end verdict（含 builder + reviewer 全部 APPROVED）relay 给 memory 后，memory **MUST** 跑 `spec_admin.py verify`：

- 全部 AC 通过 → memory 写 KB synthesis、`close` spec、通知 user 任务完成
- 任意 AC 失败 → memory **不接受 relay**，触发 rework：
  - 写出失败 AC 清单 + detail
  - 通过 `dispatch_task.py --rework <orig_task_id> --rework-reason "AC-N: <detail>"` 派 rework 给 planner（详见 dispatch_task.py 文档）
  - planner 收到 rework brief（含失败 AC 引用），重新决定 dispatch 给哪些 seat 补足

**双闸门关系**：reviewer 验证 code quality（diff / test / visual），memory 验证 spec 满足度。**两者正交、都要过**。如果 reviewer APPROVED 但 memory 验收失败，以 memory 为准（spec 是契约，code quality 是必要不充分条件）。

## 与 clawseat-intake 的衔接

`clawseat-intake` 出来的「2-4 选项每轮一问」最终需求收敛后，memory **必须** 把澄清后的需求落入 SPEC.md。intake 是过程，spec 是结果。

intake 对话历史可以归档进 `~/.agents/memory/projects/<project>/decision/`，但**契约文档是 SPEC.md，不是 intake transcript**。
