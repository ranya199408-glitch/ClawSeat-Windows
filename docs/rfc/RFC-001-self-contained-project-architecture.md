# RFC-001: Self-Contained Project Architecture (ClawSeat v2)

- **Status**: Draft (architecture aligned 2026-04-26)
- **Author**: ancestor (cartooner-ancestor session) on behalf of operator (ywf)
- **Date**: 2026-04-25 (initial), 2026-04-26 (vocabulary alignment + role re-split)
- **Branch**: `refactor/clawseat-v2-self-contained`
- **Worktree**: `<HOME>/`

---

## 1. Vocabulary (canonical, after 2026-04-26 alignment)

| Term | Definition |
|------|-----------|
| **始祖 / ancestor** | A SEAT TYPE — every project has 1, named `<project>-memory`. Owns 4 capabilities below. v1 called it "ancestor", v2 names it after its core capability (memory). |
| **memory (capability)** | The seat's persistent project knowledge store: TASKS / STATUS / decisions / history / learnings. Lives in `~/.agents/memory/<project>/` (M1) or pluggable memory skill (M2). **Not a separate seat** — it's owned by the primary seat. |
| **research (capability)** | The seat's active investigation: grep code, run commands, query docs, fetch web. Distinct from memory: research = gathering new info, memory = recalling old info. **Not a separate seat** — owned by the primary seat. |
| **dispatch (capability)** | Route work to project workers (planner / builder / designer) or to other projects' primary seats. Owned by the primary seat. |
| **dialog (capability)** | First user-facing surface for the project. The primary seat's iTerm window is the user's conversation entry point. Owned by the primary seat. |
| **project** | A self-contained 4-seat unit: 1 primary (memory) + 3 workers (planner / builder / designer). |
| **No global seats** | No global ancestor, no global memory. Every project is fully autonomous. Cross-project work = direct memory ↔ memory dispatch. |

### Seat naming (canonical)

```
<project>-memory                     primary seat (the project's brain)
<project>-planner-claude             worker: planning + code review
<project>-builder-codex              worker: code execution
<project>-designer-gemini            worker: aesthetic / visual review
```

The `-<tool>` suffix on workers makes the underlying LLM choice transparent. The primary seat omits this suffix because (a) it's the unique entry point so no need to disambiguate, and (b) operator may swap memory's tool less frequently than workers.

---

## 2. Per-project Topology

```
项目 = install (例)
┌──────────────────────────────────────────────────────────────────┐
│ install-memory  (= 旧 ancestor + 旧 memory 合并)                 │
│ ───────────────────────────────────────────────────────────────  │
│ - claude oauth · HOME=<HOME> · max privilege                 │
│ - capabilities: memory + research + dispatch + dialog            │
│ - memory impl: M1 filesystem placeholder, M2 mature skill        │
│ - research impl: M1 Bash+Read+Grep+Glob, M2 + WebFetch + MCP    │
│ - 独立 iTerm 窗口 (项目第一入口, 用户对话面)                      │
└─────┬───────────────────┬───────────────────┬───────────────────┘
      │ dispatch          │ dispatch          │ dispatch
      ▼                   ▼                   ▼
┌──────────────────┐ ┌─────────────────┐ ┌─────────────────────┐
│ install-planner- │ │ install-builder-│ │ install-designer-   │
│ claude           │ │ codex           │ │ gemini              │
│                  │ │                 │ │                     │
│ 规划 + code review│ │ 代码编写 + 跑命令│ │ 审美 + 视觉评审    │
│ (Claude 强项:    │ │ (Codex GPT-5.4  │ │ (Gemini 多模态强)   │
│  思维 + 长上下文 │ │  codegen 强)    │ │                     │
│  审查)           │ │                 │ │                     │
└──────────────────┘ └─────────────────┘ └─────────────────────┘
       (3 workers, 共享 1 个 iTerm 窗口的 3 panes)
```

### Why this role split (vs v1)

| v1 7-seat | v2 4-seat | Reasoning |
|-----------|-----------|-----------|
| ancestor (orchestrator) | merged into memory | Per-project; same agent does both |
| machine-memory-claude (global oracle) | deleted | Memory is per-project; machine state via Tier 3 watchdog |
| planner (dispatcher) | planner (planner + code reviewer) | Claude excels at READING code; let it review |
| builder (executor) | builder (codex codegen) | Codex GPT-5.4 excels at WRITING code |
| reviewer (separate code review seat) | merged into planner | Reviewer was redundant with planner-as-reviewer |
| qa (test runner) | dropped (M1) | Move tests into planner's responsibility; M2 may add back |
| designer (aesthetic) | designer (gemini) | Unchanged |

Key insight: **Use each LLM for its strength**. Claude reads/judges. Codex writes. Gemini sees. No LLM doing what it's worst at.

---

## 3. iTerm Window Topology (multi-project)

**两类窗口，N 项目 = 1 memories 窗口 + N workers 窗口**：

```
窗口 1: clawseat-memories  (全局共享, 所有项目的 memory 都在这)
       ┌────────────────────────────────────────┐
       │  install-memory                        │
       │  ❯ 第一入口                            │
       │                                        │
       │                                        │
       │                                        │
       │                                        │
       └────────────────────────────────────────┘
       
窗口 2-N: clawseat-<project>-workers  (每个项目独立)
       ┌──────────────────┬─────────────────────┐
       │                  │     builder-codex   │
       │                  │                     │
       │ planner-claude   ├─────────────────────┤
       │ (main 50%)       │     designer-gemini │
       │                  │                     │
       └──────────────────┴─────────────────────┘
```

### 3.1 workers 右侧填充策略

当前 install 模板通过 `window_layout.workers_grid.right_fill_order` 选择右侧
worker pane 的填充方式：

- `col-major`（默认）：planner/main 左 50%，右侧单列从上到下填充。
- `grid-2-rows`：历史 max-2-rows 栅格，保留给显式 opt-in 的 legacy layout。

### 3.1.1 legacy grid-2-rows 公式（max 2 rows，cols expand）

```python
def grid_for_n(n: int) -> tuple[int, int]:
    """Returns (cols, rows). Hard cap: max 2 rows. Expand cols only."""
    if n <= 0: return (0, 0)
    if n == 1: return (1, 1)
    if n == 2: return (1, 2)               # 单列垂直堆叠
    return ((n + 1) // 2, 2)               # n>=3: lock 2 rows, ceil(n/2) cols
```

| n | cols × rows | 备注 |
|---|-------------|------|
| 1 | 1×1 | 满屏 |
| 2 | 1×2 | 单列垂直堆叠 |
| 3 | 2×2 (1 empty) | 开始 expand 列 |
| 4 | 2×2 | 满 |
| 5 | 3×2 (1 empty) | |
| 6 | 3×2 | 满 |
| 7 | 4×2 (1 empty) | |
| 8 | 4×2 | 满 |
| ≥9 | ceil(n/2) × 2 | 警告 + 建议 tabs/拆窗 |

### 3.2 Memories 窗口（所有项目 memory 共用）

直接套用通用公式：

```
N=1                         N=2                         N=3
┌──────────────────────┐    ┌──────────────────────┐    ┌──────────┬───────────┐
│  install-memory      │    │  install-memory      │    │ install- │ cartooner-│
│                      │    ├──────────────────────┤    │ memory   │ memory    │
│                      │    │  cartooner-memory    │    ├──────────┤           │
└──────────────────────┘    └──────────────────────┘    │  mor-    │ (empty)   │
                                                        │  memory  │           │
                                                        └──────────┴───────────┘

N=4                                         N=6
┌──────────┬───────────┐                    ┌────────┬────────┬─────┐
│ install- │ cartooner-│                    │   m1   │   m2   │ m3  │
│ memory   │ memory    │                    ├────────┼────────┼─────┤
├──────────┼───────────┤                    │   m4   │   m5   │ m6  │
│  mor-    │   m4      │                    └────────┴────────┴─────┘
│  memory  │           │
└──────────┴───────────┘
```

填充顺序：col-major（先填左列上→下，再填中列上→下，再填右列上→下）。

新项目 install 时**重排整窗**（teardown old window + create fresh with N+1 panes）。tmux session 持续运行所以无对话历史丢失。

### 3.3 Workers 窗口（planner main + 右侧公式化）

planner 永远占左侧 50%，右侧用通用公式排剩下 N-1 个 worker：

```
N_total=2 (planner + 1)             N_total=3 (planner + 2 workers; v2 minimal)
┌──────────────┬──────────────┐     ┌──────────────┬──────────────┐
│              │              │     │              │   builder    │
│   planner    │   builder    │     │   planner    ├──────────────┤
│   (main)     │              │     │   (main)     │   designer   │
└──────────────┴──────────────┘     └──────────────┴──────────────┘

N_total=4 (planner + 3)             N_total=5 (planner + 4)
┌──────────────┬───────┬───────┐    ┌──────────────┬───────┬───────┐
│              │builder│design │    │              │builder│design │
│   planner    ├───────┼───────┤    │   planner    ├───────┼───────┤
│   (main)     │review │       │    │   (main)     │review │  qa   │
└──────────────┴───────┴───────┘    └──────────────┴───────┴───────┘
```

**布局参数（locked decisions 2026-04-26）**:
- 左/右宽度比 = **50/50** (固定，所有 N 一致)
- 右侧 worker 排序 = **按 template 顺序** (builder → designer → reviewer → qa → ...)
- 右侧填充 = **col-major** (先填左列上→下，再下一列)
- 默认 active pane = **planner**

新 worker 添加时**重排整窗**。

### 3.4 关键含义

- **N 项目 = N+1 窗口**（不是 v1 设想的 2N，因为 memories 共享）
- **单一对话入口**：扫一眼 memories 窗口就看到所有项目当前状态
- **无全局协调者**：跨项目协作通过 `tmux-send <other>-memory ...` 直接 dispatch（无中介）
- **iTerm pane 只是 client**：tmux session 是 source of truth，pane 关闭/重建不丢对话状态

### 3.5 项目注册表 (新增)

`~/.clawseat/projects.json` 记录所有 active 项目：

```json
{
  "version": 1,
  "projects": [
    {"name": "install",   "primary_seat": "memory", "tmux_name": "install-memory",   "registered_at": "2026-04-26T01:00:00Z"},
    {"name": "cartooner", "primary_seat": "memory", "tmux_name": "cartooner-memory", "registered_at": "2026-04-26T02:00:00Z"}
  ]
}
```

install.sh 创建项目时追加；uninstall 时删除。memories 窗口的 build/refresh 读这个文件决定布局。

---

## 4. Architecture Tiers

### Tier 1 — Per-Project Primary Seats

每个 `<project>-memory`:
- Claude OAuth, REAL_HOME=<HOME>, --dangerously-skip-permissions
- Owns: memory + research + dispatch + dialog
- Dialog: receives user input via its iTerm window
- Cross-project: direct `tmux-send <other>-memory` dispatch
- System actions: writes to `~/.clawseat/state/cmdq.jsonl` for Tier 3 to execute

### Tier 2 — Per-Project Workers

`<project>-planner-claude`, `<project>-builder-codex`, `<project>-designer-gemini`:
- Own respective LLM tool (Claude / Codex / Gemini)
- Receive dispatch from project's memory seat
- Don't directly face user (report back to memory)
- Don't dispatch cross-project (must go through memory)

### Tier 3 — Execution (No-LLM Watchdogs)

机器级 daemon 集群（无 LLM, 纯 shell, 跑在用户 launchd 下）:
- `watchdog-iterm-grid` — 监控所有 `<project>-memory` 和 `<project>-workers` 窗口存在性, 缺失自动 recover
- `watchdog-cron-drift` — 校验 crontab 期望与现状
- `watchdog-tmux-health` — 关键 session alive 监控
- `watchdog-secrets-ttl` — token 即将过期预警
- `watchdog-disk-quota` — `~/.clawseat` 占用监控
- `watchdog-slash-injector` — 接收 cmdq.jsonl 中的 `kind:"slash"` 指令, 通过 tmux send-keys 投递 `/clear` `/new` 等

输入/输出契约 (`~/.clawseat/state/`):
- 写: `observations.jsonl` (Tier 3) / `alerts.jsonl` (Tier 3)
- 读: `policy.json` (Tier 1 写, Tier 3 读) / `cmdq.jsonl` (Tier 1 写, Tier 3 读)
- 反馈: `cmdq-results.jsonl` (Tier 3 写, Tier 1 读)

### Tier 0 — Templates

模板系统:
- repo 内置: `retired-v2-starter` (v2 第一个), 未来可加 `clawseat-engineering` (重写适配 v2) / `clawseat-creative` 等
- 用户自定义: `~/.agents/templates/<name>.toml` ✅ M3 解锁
- 模板继承: `extends = "retired-v2-starter"` + override seat 字段 ✅ M3
- 模板版本: `version` 字段 + 升级路径 (v1 = 1, v2 = 1 仍兼容)

---

## 5. Slash-Command Awareness

来自 operator 的明确要求："让 ClawSeat 知道如何使用 /new、/clear 等基础功能"。

> Claude Code 的 slash-command **只能由真正的键盘输入触发** — LLM 在响应里写 `/clear` 文本不会被解释为命令。

设计:
- Tier 3 加 `watchdog-slash-injector` daemon, 订阅 `cmdq.jsonl` 中 `kind: "slash"` 的指令
- memory seat 决策"该让某 worker /clear context"时, 写一行 cmdq:
  ```json
  {"kind":"slash","target_seat":"install-builder-codex","command":"/clear","reason":"context > 200k tokens"}
  ```
- watchdog 通过 `tmux send-keys` 真正按键投递 (而非文本投递)
- 用途: 定期 /clear 长上下文 worker、紧急 /new 重置卡死 seat 等

---

## 6. Implementation Milestones

### M1 — Skeleton (本 RFC + 已落 commit)

完成情况：

- [x] `templates/retired-v2-starter.toml` 落到 v2 worktree (canonical, 4 seat)
- [x] install.sh 接受 `retired-v2-starter` 模板 (whitelist 含 minimal)
- [x] install.sh `prompt_kind_first_flow` 改 2-mode (新手 default = retired-v2-starter / 专家 = clawseat-engineering)
- [x] install.sh `bootstrap_project_profile` 修复 reinstall session.toml 复活 bug
- [x] install.sh PRIMARY_SEAT_ID generalization (8 处 hardcoded `${PROJECT}-ancestor` 改 `${PROJECT}-${PRIMARY_SEAT_ID}`)
- [x] Python `agent_admin_window.py` + `agent_admin_session.py` 5 处 `"ancestor"` 字面量改成 `_PRIMARY_SEAT_IDS = {"ancestor", "memory"}` 集合判断
- [ ] **NEXT**: 测试 — `clawseat project new testbed --template retired-v2-starter` → 4 seat 正常 spawn → memory 收到用户对话
- [ ] auto_send_phase_a_kickoff: 扩 polling 窗口到 OAuth 信任屏完成 (当前 72s 不够)
- [ ] memory seat 启动时挂 Stop hook
- [ ] memory seat 接受 dispatch 协议 (跟 v1 dispatch_task 兼容)
- [ ] iTerm 窗口拓扑改成 1 memory window + 1 workers window (现在仍是 v1 单窗 4 panes — install.sh window_payload 需要拆分)

### M2 — Watchdog Tier

- [ ] `~/.clawseat/state/` 目录契约 (policy.json / cmdq.jsonl / observations.jsonl / alerts.jsonl / cmdq-results.jsonl)
- [ ] `watchdog-iterm-grid` daemon
- [ ] `watchdog-cron-drift` daemon
- [ ] `watchdog-secrets-ttl` daemon
- [ ] `watchdog-slash-injector` daemon
- [ ] launchd plist 装载脚本

### M3 — 自定义模板 + 继承

- [ ] `templates/*.toml` 文件扫描注册 (去掉硬编码白名单)
- [ ] template `extends = "retired-v2-starter"` 继承机制
- [ ] `agent_admin template list/show/validate/create` 子命令
- [ ] 文档: 如何写自定义模板

### M4 — 干掉 v1 旧拓扑

- [ ] 现有 install/cartooner/mor 项目迁移工具 (v1 → v2 自闭环)
- [ ] 删除 v1 全局 machine-memory-claude
- [ ] 文档: v1 → v2 升级指南

---

## 7. Open Questions (M1 不阻塞，M2 决定)

| # | 问题 | M1 临时方案 | M2 决策 |
|---|------|------------|---------|
| Q1 | 机器级 watchdog 归谁? | install 时装机器级 launchd plist | 确认 launchd plist 内容 |
| Q2 | bootstrap 时是否默认创建第一个项目? | 否 (install.sh 只装基础设施, 用 `clawseat project new <name>` 创建) | 确认 |
| Q3 | memory skill 现在选型? | 后期接口预留 (M1 用 `~/.agents/memory/<project>/notes.md` placeholder) | 选型 mem0 / letta / built-in / vector DB |
| Q4 | 大规模 (5+ 项目) iTerm UX | 自然摆放 | 探索 dock 风格 / Spaces 分桌面 |
| Q5 | per-project memory 的写权限范围 | 跟当前 OAuth engineer 一样 (REAL_HOME + dangerously-skip) | 加 ACL gate (只能写 cmdq.jsonl, 系统级 mutating 走 watchdog) |
| Q6 | 跨项目协作的限速 | memory ↔ memory 自由 dispatch | 加 rate limit / circuit breaker |

---

## 8. Migration Plan

### 短期: v1 + v2 并存

- 当前 install / cartooner / mor (在 experimental 分支上) 保留作 baseline
- v2 新建项目用 `--template retired-v2-starter`, 跑在 v2 worktree 的代码上
- 两套并存验证 1-2 周

### 长期: 完全切换 v2

- v2 stable 后 mark `clawseat-{default,engineering,creative}` 为 deprecated
- 至少 1 个发布周期保持兼容
- 然后正式删除 v1 拓扑代码 + 删除 machine-memory-claude

---

## 9. Decision Log

| 日期 | 决议 | 来源 |
|------|------|------|
| 2026-04-25 22:50 | 取消"全局 ancestor + 全局 memory"路线，改为"项目自闭环 + per-project memory" | operator |
| 2026-04-25 23:30 | per-project memory 名 = `<project>-memory`（不再叫 `<project>-ancestor`）| operator |
| 2026-04-25 23:35 | 没有 builder seat（planner 自己写代码）| operator |
| 2026-04-25 23:35 | 没有 qa seat（M1 范围）| operator |
| 2026-04-25 23:42 | 没有 global ancestor（"如果有多个项目，所有 memory 都是第一入口直接跟用户沟通"）| operator |
| 2026-04-25 23:42 | 每个项目 2 个 iTerm 窗口（memory 独立窗口 + workers grid 窗口）| operator |
| 2026-04-25 23:48 | planner 默认 claude，支持任意模型切换 | operator |
| 2026-04-25 23:48 | reviewer 默认 codex，支持 oauth/api 切换；api 默认 xcode-best | operator |
| 2026-04-26 00:35 | **撤销 23:35 决定**: codex 应是 builder 不是 reviewer; planner 兼任 review; ancestor 加 research 能力 | operator |
| 2026-04-26 00:48 | **词汇对齐**: ancestor 是 SEAT 类型 (per-project); memory + research 是 capability (住在 ancestor 上); 没有独立 memory seat; 没有全局 ancestor | operator |
| 2026-04-26 00:48 | **命名规则**: 所有 seat 统一 `<project>-<role>[-<tool>]`; primary seat = `<project>-memory` (不带 tool 后缀) | operator |
| 2026-04-26 01:10 | 4-seat = `<project>-memory` + planner-claude + builder-codex + designer-gemini | operator |
| 2026-04-26 01:30 | install.sh + agent_admin Python 引入 PRIMARY_SEAT_ID / `_PRIMARY_SEAT_IDS` 抽象，让模板可指定 ancestor 或 memory 任一作为 primary | ancestor 实施 |

---

## 10. Review Workflow

本 RFC 完成草案后:

1. operator review (你正在看的就是)
2. operator 拍板后, dispatch 给 install team 实施 M1 剩余任务
3. install team planner-claude 出实施细则 → builder-codex 编码 → planner-claude review → memory archive
4. M1 完成后 operator 验收 (用 `clawseat project new testbed --template retired-v2-starter` 创个最小项目跑通对话)
5. M1 验收通过 → 启动 M2

---

**End of RFC-001**
