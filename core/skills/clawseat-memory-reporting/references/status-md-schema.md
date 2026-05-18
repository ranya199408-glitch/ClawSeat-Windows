# STATUS.md Schema (v1)

> **path**: `${AGENT_HOME}/.agents/tasks/<project>/STATUS.md`
> **writer**: memory seat (唯一写入者)
> **readers**: operator, 其他 seat (read-only), 跨会话 reload
> **maintained by**: [clawseat-memory-reporting](../SKILL.md) §2

---

## 设计原则

1. **整文件 ≤ 100 行**，超出说明 dispatch log 该 truncate
2. **section 顺序固定**，缺失 section 显式标 `(none)`，不 silently 省略
3. **append-only dispatch log**：保留最后 20 条，更老的归档到 `STATUS-history.md`（暂未实现，M1 不强求）
4. **ISO 8601 时间戳**：`2026-04-26T03:35:18+08:00`，不用 epoch / 不用 relative
5. **每次写入 atomic**：先写 `STATUS.md.tmp` 再 `mv`，避免读到半态

---

## 完整 schema

```markdown
# <project> — STATUS

> updated: <ISO 8601 ts> by memory  |  brief mtime: <ISO 8601 ts>

## phase

phase=<ready | bootstrap | blocked> [since <ts>]
[blocked reason: <one line>]

## roster

| seat | tool | auth | session | alive |
|------|------|------|---------|-------|
| memory   | claude | oauth/anthropic | <project>-memory          | ✅ |
| planner  | claude | oauth/anthropic | <project>-planner-claude  | ✅ |
| builder  | codex  | oauth/openai    | <project>-builder-codex   | ✅ |
| designer | gemini | oauth/google    | <project>-designer-gemini | ✅ |

[memory 角色注: planner-reviewer 由 planner 兼任 (v2 minimal 没有独立 reviewer seat)]

## active dispatches

- pkg-c-batch1-memories-tabs → planner (todo: install/planner/TODO.md) — sent 2026-04-26T03:37:42+08:00
- (none other)

或 (无活跃 dispatch 时):

(none)

## pending operator decisions

- (none)

或 (有待决):

- 是否启动批次 2 (#3 + #6 + #15 vocab refresh)?
- 新项目 testbed 应该用哪个 template?

## recent issues (last 5)

| # | severity | status | title |
|---|----------|--------|-------|
| #14 | 🟠 HIGH   | fixed @ 4113225 | wait-for-seat TMUX 继承 |
| #2  | 🟠 HIGH   | fixed @ 4113225 | auto_send 72s |
| #11 | 🟠 HIGH   | fixed @ dbe126d | reseed-pane API |
| #5  | 🟠 HIGH   | fixed @ 5adb05d | stale rename |
| #4  | 🟠 HIGH   | in-progress (Package C) | memories tabs |

## current milestone

M1 batch 1 (A/B/D ✅, C 🔄)

## next checkpoint

C 完成后启动 batch 2 (#3 banner stale + #6 memories ensure-tab + #15 vocab refresh)
ETA: C 预计 2026-04-26T05:00 完成（planner → builder → designer review chain）

## dispatch log (append-only, last 20)

- 2026-04-26T02:29:04+08:00: memory dispatched pkg-a-batch1-stale-rename to planner
- 2026-04-26T02:33:46+08:00: planner dispatched pkg-a-batch1-stale-rename to builder
- 2026-04-26T02:42:56+08:00: memory dispatched pkg-d-batch1-reseed-pane to planner
- 2026-04-26T02:45:11+08:00: planner dispatched pkg-d-batch1-reseed-pane to builder
- 2026-04-26T03:33:18+08:00: memory dispatched pkg-b-batch1-autosend-tmux to planner
- 2026-04-26T03:33:37+08:00: planner dispatched pkg-b-batch1-autosend-tmux to builder
- 2026-04-26T03:35:18+08:00: builder ack pkg-b-batch1-autosend-tmux verdict=PASS commit=4113225
- 2026-04-26T03:37:42+08:00: memory dispatched pkg-c-batch1-memories-tabs to planner
- 2026-04-26T03:39:08+08:00: planner dispatched pkg-c-batch1-memories-tabs to builder
```

---

## 字段定义

### phase

| 值 | 含义 |
|---|------|
| `bootstrap` | install.sh 还在跑 / Phase-A 未完成 |
| `ready` | Phase-A 完成，所有 seat alive，可接 dispatch |
| `blocked` | 出现阻塞（必须有 reason 行） |

`since <ts>`: 进入当前 phase 的时刻。

### roster

每行一个 seat。`alive` 用 `tmux has-session -t '=<session>'` 判定，✅/❌。

`memory 角色注` 行可选；用于说明非 1:1 角色映射（如 v2 minimal 没有独立 reviewer，planner 兼任）。

### active dispatches

memory 派出但 target 还没 ack 的 dispatch。每行格式:
```
- <dispatch_id> → <target_seat> (todo: <relative_path>) — sent <ts>
```

target ack 后：从 active 移除 + dispatch log 加 ack 行。

### pending operator decisions

memory 需要 operator 拍板才能继续的事。空时显式写 `(none)`。

operator 拍完一项 → 立即从此 section 删除 + 进入 dispatch log（如果转化为派工）。

### recent issues

最近 5 条 issue（按编号倒序，不是按 status）。让 operator 一眼看到 M1 进度。

更详细的 issue 列表去 `docs/rfc/M1-issues-backlog.md`，本 section 只摘要。

### current milestone

当前正在打的 milestone。M1 期间通常是 `M1 batch N (X/Y/Z 状态)`。

### next checkpoint

memory 预期下一个会发生的事 + ETA。让 operator 知道"什么时候该回来看进度"。

### dispatch log

Append-only 记录所有 dispatch + ack 事件。保留最后 20 条；更老的截断（M1 阶段先不归档）。

格式严格：
```
- <ISO ts>: <subject> <verb> <object> [verdict=<v>] [commit=<sha>]
```

`verb`:
- `dispatched` (memory → planner / planner → builder)
- `ack` (target → sender)
- `forwarded` (planner middleware behavior)

---

## 写入示例（memory 应该这样维护）

### 场景 A: 派出新 dispatch

memory 跑 `bash gstack/dispatch_task.py ...` 后:

1. 在 `## active dispatches` 加 1 行
2. 在 `## dispatch log` append `<ts>: memory dispatched <id> to <target>`
3. 更新顶部 `> updated: <new ts>`
4. atomic write

### 场景 B: target ack

memory 收到 planner 的 DELIVERY ack 后:

1. 从 `## active dispatches` 删除该行
2. 在 `## dispatch log` append `<ts>: <target> ack <id> verdict=<v> commit=<sha>`
3. 如果该 dispatch 关联 issue，更新 `## recent issues` 状态
4. 更新顶部 `> updated: <new ts>`
5. atomic write

### 场景 C: phase transition

install.sh 跑完 + memory 完成 Phase-A B7:

1. `## phase` 改 `phase=ready since <ts>`
2. 更新 `## current milestone` 进入 M1
3. 更新顶部 `> updated: <new ts>`

### 场景 D: 阻塞

某 dispatch 卡住或 operator 报新阻塞:

1. `## phase` 改 `phase=blocked` + `blocked reason: ...`
2. `## active dispatches` 标 `[BLOCKED]` 后缀
3. `## pending operator decisions` 加待决项

---

## 实现备注

- 当前（2026-04-26）`~/.agents/tasks/install/STATUS.md` 是 **ad-hoc 格式**，不符合本 schema
- batch 2 的 #16 任务包含：把现存 STATUS.md 迁移到本 schema
- memory 在 batch 2 落地前可以**人工维护**本 schema（不依赖工具）
- 后续 `agent_admin status update` CLI 工具可以封装 atomic write，避免手抖

---

## 跟其他工具的关系

| 工具 | 跟 STATUS.md 关系 |
|------|-----------------|
| `agent_admin project show` | 读 project.toml，**不读** STATUS.md |
| `dispatch_task.py` | 写 receipt 到 `patrol/handoffs/`，**不写** STATUS.md（memory 手动追加 dispatch log） |
| `send-and-verify.sh` | 通信工具，跟 STATUS.md 无关 |
| `events_watcher.py` | 监听 patrol/handoffs/*.json，**未来** 可以自动追加 dispatch log（M2 优化） |
| operator `cat STATUS.md` | 主要读取场景 |
| 跨会话 reload | memory 启动后先 `cat STATUS.md` 重建状态认知 |

---

## 验收

memory 自我检查（每次写完 STATUS.md 后）:

- [ ] section 顺序对吗？
- [ ] 整文件 ≤ 100 行吗？
- [ ] 时间戳是 ISO 8601 吗？
- [ ] dispatch log 最多 20 行吗？
- [ ] 顶部 `updated` ts 跟最新事件一致吗？
- [ ] active dispatches 跟 dispatch log 末尾一致吗（无矛盾状态）？
