# M1 Issues Backlog

> 所有 v2 实施过程中发现的问题（含 operator 反馈、ancestor 自检发现、install-memory 报告的 ARCH-VIOLATION 等），等 install team 4 seat 齐后**统一派单修复**。

- **Worktree**: `<HOME>/`
- **Branch**: `refactor/clawseat-v2-self-contained`
- **Owner (post-Phase-A)**: install-memory → planner-claude → builder-codex → planner-claude review
- **Last updated**: 2026-04-26 (持续追加)

---

## 严重度分类

- **🔴 BLOCKER**: 阻塞 Phase-A 完成或 install team 工作
- **🟠 HIGH**: 影响用户体验或功能正确性，M1 内必修
- **🟡 MEDIUM**: 小瑕疵或文案漂移，M1 内可修
- **🟢 LOW**: 清扫项 / nice-to-have，M2 / M3 再修

---

## Issue 清单

### #1 brief 模板硬编码 5-worker，与 minimal 4-seat 不一致 — 🟠 HIGH

**症状**:
- `core/templates/memory-bootstrap.template.md` 写死 `planner, builder, reviewer, qa, designer` (5 workers)
- minimal 模板只有 `planner, builder, designer` (3 workers, no reviewer/no qa)
- 渲染出的 `~/.agents/tasks/install/patrol/handoffs/memory-bootstrap.md` 让 memory seat 按 5-seat 心智 spawn，会失败

**当前缓解**: ancestor 在 install 时手动 sed 修补（删除 reviewer/qa 字面量），但模板源头没改

**修复**:
- 改 `render_brief()` (install.sh Step 4) 让它读 PENDING_SEATS 动态渲染
- 或在 brief 模板里用 `{{seats}}` placeholder + Python 渲染时替换

**Owner**: builder-codex

---

### #2 auto_send_phase_a_kickoff 72s polling 窗口对 OAuth 太短 — ~~🟠 HIGH~~ **SUPERSEDED by #17**

**症状**:
- `auto_send_phase_a_kickoff()` (install.sh:1403) max_polls=24 × poll_seconds=3 = 72s
- 全新 identity HOME 启 Claude Code OAuth 时弹"Quick safety check / Trust folder"，operator 手动确认完平均 30-90s

**临时修复 (commit 4113225, Package B)**: max_polls 24 → 60（180s）

**状态**: ⚠️ **SUPERSEDED** — #17 (Package P1) 直接删除整个 `auto_send_phase_a_kickoff()` 函数 + Step 9.5，改为 confirm-then-dispatch 协议。P1 commit 落地后 4113225 的改动同时被删，这是预期（重构方向变了）。#2 视为 closed by #17。

**Owner**: builder-codex

---

### #3 install.sh operator-guide banner 仍说 install-ancestor — 🟡 MEDIUM

**症状**: install.sh 末尾的 fallback banner 文案（约 1261-1313 行）所有 "install-ancestor pane" 引用没跟 PRIMARY_SEAT_ID 同步：
```
tmux capture-pane -t install-ancestor -p | tail -10
tmux kill-session -t install-ancestor
重新启动 ancestor (建议重跑 scripts/install.sh ...)
```

**修复**: banner 内的 `install-ancestor` 全替换为 `${PROJECT}-${PRIMARY_SEAT_ID}` 模板变量

**追加 (2026-04-26 Package A audit)**：planner 跑 grep 时发现更多同类 stale，Package A 有意超出 TODO scope 未动；合并到 #3 一起修：
- `scripts/install.sh` L1305, L1338, L1351, L1479, L1505 (operator-guide message strings)
- `scripts/launch-grid.sh:27` — v1 5-seat `SEATS=(ancestor planner builder reviewer qa designer)`
- `scripts/launch_ancestor.sh:149` — v1 ancestor launcher
- `core/launchers/agent-launcher.sh:683` — comment
- `core/scripts/agent_admin_session.py:683` — comment
均为非运行时关键路径，不阻塞功能，批次 2 处理。

**Owner**: builder-codex

---

### #4 memories 窗口应该用 tabs 而不是 split panes — 🟠 HIGH

**症状**:
- 当前 `memories_payload()` 用 split panes（grid_for_n 公式）
- operator 期望: 用 iTerm tabs，每个 tab = 1 个项目 memory，tab 标题清晰显示项目名

**期望最终态**:
```
Window: clawseat-memories
┌─ install ─┬─ cartooner ─┬─ mor ─┐  ← tab bar
├───────────┴─────────────┴───────┤
│                                  │
│   <selected project>-memory pane │  ← full window
│                                  │
└──────────────────────────────────┘
```

**修复**:
- `iterm_panes_driver.py` 加 `mode: "tabs"` 选项（用 `window.async_create_tab()` 而非 `session.async_split_pane()`）
- `memories_payload()` 输出 `mode: "tabs"`
- memories rebuild 协议改成"ensure tab for this project exists"（add/remove 单 tab，不重建整窗）
- tab 标题 = 项目名（不带 "-memory" 后缀）

**Owner**: builder-codex（实施）+ planner-claude（review tab 命名约定）

---

### #5 brief 的 "session status" 检查 assertion 过时 — 🟡 MEDIUM

**症状**: install-memory 跑 Phase-A 时报 ARCH-VIOLATION:
> brief 期望 `install-ancestor` session 存在,实际只有 `install-memory`

**根因**: brief 是 v1 心智下渲染的，"session status check" 会跑 `agent_admin session-name ancestor --project install`，对 v2 minimal 返回 `ancestor has no session in project install`

**修复**:
- brief 模板的 session check 步骤改用 PRIMARY_SEAT_ID（与 #1 一起做）
- 或把 brief 拆成 v1 / v2 两个变体（不推荐，维护负担）

**Owner**: builder-codex

---

### #6 install.sh 当前 memories 窗口实现是 close+rebuild — 🟢 LOW

**症状**: `Step 7b: rebuild shared memories window` 的实现是
```bash
osascript -e 'tell application "iTerm2" to close (every window whose name is "clawseat-memories")'
open_iterm_window "$(memories_payload)" _mem_window_id
```
每次 install 都把整个 memories 窗口关掉重开。其他项目的 memory pane 里如果用户正在打字，会丢草稿。

**修复**: 实现"ensure tab for this project exists"协议（与 #4 tabs 一起做更自然）
- 若窗口不存在 → 创建带 1 tab
- 若窗口存在且当前项目 tab 不在 → 追加 1 tab
- 若 tab 已存在 → 无操作

**Owner**: builder-codex（与 #4 合并）

---

### #7 projects.json 注册表未实现 — 🟢 LOW

**症状**: RFC §3.5 说要有 `~/.clawseat/projects.json` 跟踪所有项目；当前 memories_payload 用 `tmux ls grep -memory$` 临时枚举

**修复**:
- install.sh 创建项目时 append 到 `~/.clawseat/projects.json`
- uninstall 时删除
- memories_payload 优先读这个文件，fallback tmux 枚举

**Owner**: builder-codex

**优先级低**: 现有 tmux 枚举工作，正式注册表是 nice-to-have

---

### #8 Tier 3 watchdog 集群未实现 — 🟢 LOW (M2 范围)

**症状**: RFC §4 Tier 3 设计了 5 个 watchdog daemons（iterm-grid / cron-drift / tmux-health / secrets-ttl / slash-injector），全部未实施

**修复**: 见 RFC §6 M2 milestones 清单

**Owner**: 整个 install team（builder 实现 + planner review + designer review）

---

### #9 v1 全局 machine-memory-claude 仍在跑 — 🟢 LOW (M4 范围)

**症状**: v2 RFC 说删除 v1 全局 memory seat，但当前 machine-memory-claude tmux session 仍在跑

**修复**: M4 阶段（v2 stable 后）正式 deprecate + 删除

---

### #10 workers_payload planner pane 错用 tmux attach 而非 wait-for-seat — 🔴 BLOCKER

**症状**:
- v2 workers_payload() 把 planner pane 的 command 写成 `tmux attach -t '={project}-planner-claude'`
- 但 planner-claude tmux session 在 install.sh 跑完时**还不存在**（要等 memory seat 在 Phase-A 中 spawn）
- 结果 planner pane 立刻 tmux attach 失败 → fall through 到 zsh，不会自动 attach 成功后的 planner

**对比 builder/designer**: 它们用 `bash wait-for-seat.sh install builder` 正确轮询直到 session 存在再 attach

**根因**:
- 我写 workers_payload 时沿用了 v1 grid_payload 的"第一个 pane 是 primary seat 用 tmux attach"模式
- 但 v1 primary seat (ancestor) 是 Step 5 install.sh 直接 launch 的，已经存在
- v2 workers 窗口里 planner 不是 primary seat (memory 才是, 在另一个窗口), planner 是要被 memory spawn 的 worker, 与 builder/designer 同地位

**修复**: workers_payload() 把 planner 的 command 也改成 `bash wait-for-seat.sh <project> planner`

**Owner**: ancestor 自己立刻修（这是我新引入的 bug, 不是历史债）

**临时缓解**: install-memory 完成 Phase-A spawn planner-claude 后, operator 手动 close workers 窗口 + 重开（此时 planner-claude session 已存在）

---

### #11 agent_admin window reseed-pane iterm2 API send_text 失效 — 🟠 HIGH

**症状**:
- `agent_admin window reseed-pane <project> <seat>` 走 iterm2 Python API 路径
- API 返回 success，但 send_text 序列（Ctrl-C + Ctrl-B+d + 命令）**没真正写入空闲 zsh shell**
- 直接用 iTerm AppleScript `write text` 才生效

**对比**: install.sh 主流程 open_iterm_window 用的是 iterm_panes_driver.py，用 `async_send_text()` 也是 API 路径——但首次创建 pane 时（pane 刚开就发命令）OK；reseed-pane 是对**已有 idle pane** 发命令时失败

**可能根因**: iterm2 Python API 的 send_text 对刚 attached 的 session 工作，但对 idle 的 zsh 可能需要先获取 keyboard focus 或 send_keys 而不是 send_text

**修复方案候选**:
- a. reseed-pane 改用 osascript AppleScript "tell application iTerm2 ... write text" (绕开 Python API bug)
- b. send_text 前先 `await session.async_activate()` 取 focus
- c. 用 send_keys 模拟物理键盘事件而非文本注入

**Owner**: builder-codex (实施) + planner-claude (测试 reseed-pane 在 v2 minimal 各场景下都工作)

---

### #12 recover-grid.sh + grid-recovery 路径硬编码 install-ancestor — 🟠 HIGH

**症状**:
- `scripts/recover-grid.sh` 和 `agent_admin_session.py` 内部 grid_recovery_log 等路径全部假设 `${PROJECT}-ancestor`
- v2 minimal 用 `${PROJECT}-memory`，recover-grid 找不到对的 session 名

**与 issue #10 关系**: 都属于"我之前 PRIMARY_SEAT_ID 重构漏改的硬编码点"批次。我审过 install.sh + agent_admin 主路径但没审 recover-grid.sh 等辅助脚本

**修复**: recover-grid.sh + 所有相关辅助脚本统一查 PRIMARY_SEAT_ID（从 `~/.agents/projects/<project>/project.toml` 或 session.toml 读 first engineer.id）

**Owner**: builder-codex

**关联**: 跟 #10 同根（PRIMARY_SEAT_ID 重构不彻底），可一起 PR

---

### #13 v2 split topology 漂移 — 5 个偏离点 — 🟠 HIGH

**operator 实证 (2026-04-26 03:00)**: 跑 `recover-grid.sh install` 后, install-memory 被双 attach (出现在 v1 风格 `clawseat-install` 单窗 + v2 风格 `clawseat-memories` 双窗)。

**根因**: v2 双窗逻辑只在 install.sh shell 函数里 (workers_payload/memories_payload), 没下沉到 Python `agent_admin_window` 模块。任何绕过 install.sh main() 的调用方都回到 v1 单窗。

**5 个偏离点**:

| # | 位置 | 问题 |
|---|------|------|
| 漂移 1 | `core/scripts/agent_admin_window.py:215-256` `build_grid_payload()` | 只懂 v1 单窗 (panes[0]=primary seat, panes[N+1]=machine-memory-claude); 没有 v2 split 选项 |
| 漂移 2 | `core/scripts/agent_admin_window.py:366` `open_grid_window()` | 不区分模板, 永远调 build_grid_payload |
| 漂移 3 | `scripts/recover-grid.sh:65` | 通过 `agent_admin.py window open-grid` 间接落入漂移 1+2 |
| 漂移 4 | 缺少 Python API `open_workers_window()` + `ensure_memories_pane()` | v2 双窗逻辑只在 install.sh, 其他调用方没法复用 |
| 漂移 5 | `agent_admin_window.py:254-255` 把 v1 `machine-memory-claude` 加进 grid | 与 v2 "删除全局 memory seat" 矛盾, 应该不加 |

**统一修复策略**:

1. 把 install.sh 的 `workers_payload()` + `memories_payload()` 逻辑**下沉到 Python**:
   - 新增 `agent_admin_window.build_workers_payload(project)` (planner main + N-1 workers grid, recipe 含 PRIMARY_SEAT_ID-aware 跳过 primary seat)
   - 新增 `agent_admin_window.build_memories_payload()` (扫所有 `<project>-memory` tmux session 排 grid_for_n)
   - 删除 `build_grid_payload()` 里的 v1 行为 OR 加 `template_kind` 参数分支

2. 改 `open_grid_window(project)` 入口:
   - 读 project 的 template_name (从 `~/.agents/projects/<project>/project.toml`)
   - retired-v2-starter → 调 `build_workers_payload + ensure_memories_pane` (v2 双窗)
   - clawseat-{default,engineering,creative} → 保留 `build_grid_payload` (v1 单窗)

3. 新增 `agent_admin_window.ensure_memories_pane(project)` 协议:
   - 检测 `clawseat-memories` 窗口存在? 不存在则创建带本项目 1 pane
   - 已存在但本项目 pane 不在? append pane (split or new tab 看 #4 决议)
   - 已存在且 pane 已在? no-op

4. `recover-grid.sh` 不需要改 (调 open-grid 自动走对路径)

5. install.sh main() retired-v2-starter 分支可以改用 Python helper (代码复用)

**追加修复**:
- 删除 `agent_admin_window.py:254-255` 把 machine-memory-claude 加进 grid 的代码 (v2 没这个)

**Owner**: builder-codex (实施) + planner-claude (review API 设计)

**关联**:
- 跟 #4 (memories tabs) 一起做, ensure_memories_pane 实现要支持 tabs 模式
- 跟 #11 (reseed-pane AppleScript) 不冲突, AppleScript 用法分开

**验收**:
- `bash scripts/recover-grid.sh install` 后: clawseat-install 窗口**不存在**; install-memory **只 attach 一次** (在 clawseat-memories); clawseat-install-workers 3-pane (planner + builder + designer)
- `agent_admin window open-grid testbed` 在新项目上同样产出双窗
- v1 模板 (engineering/default) 仍能正常 open-grid 单窗

---

### #14 wait-for-seat.sh TMUX 环境变量继承导致 switch-client fallback — 🟠 HIGH

**症状**: designer (或任何 worker) seat session 死掉后，对应 iTerm pane 自动 attach 到 `install-memory` TUI；operator 在那个 pane 的键入进入 memory 输入框。

**根因 (2026-04-26 03:35 install-memory 调研确认)**:
1. install.sh 在 install-memory tmux session 里运行，spawn workers 窗口时 iTerm 继承了 `TMUX` 环境变量（实测 designer pane tty124 里 `TMUX=/private/tmp/tmux-501/default,29587,162`）
2. wait-for-seat.sh line 207 跑 `tmux attach -t "=install-designer-gemini"`
3. tmux 检测到 `TMUX` 已设定 → 把 `attach` 解读为 `switch-client`，而非新建独立 client
4. 当 designer session 死亡 → tmux 自动把该 client 切回"上一个 session"（install-memory）
5. pane 显示 install-memory TUI，operator 键入进入 memory 输入框

**修复**: `wait-for-seat.sh` line 207，在 `tmux attach` 前清除 `TMUX`：
```bash
# 修复前
if tmux attach -t "=$TARGET_SESSION"; then
# 修复后
if env -u TMUX tmux attach -t "=$TARGET_SESSION"; then
```

**Owner**: builder-codex（1 行 fix）
**批次**: 批次 1 补丁（HIGH，与 Package B #2 同批或 micro-PR）

---

### #15 v1→v2 词汇漂移大批量清扫 — 🟠 HIGH

**症状**: v1 vocab 在 60+ 文件里残留，导致：
- skill 自我描述跟 v2 实际行为脱节（如 ancestor SKILL.md:229 说"默认六宫格 Row1-Col1=ancestor"）
- planner SKILL.md 列死 reviewer/qa 可派 seat（v2 minimal 没有这俩）
- preflight + skill_registry + profile_validator 硬编码 5-worker
- README.md 顶层声明 "6 seat roster"

**根因**: v2 RFC §1 §2 vocab（始祖=memory seat / workers+memories 双窗 / template-driven roster）只在新写的代码/文档对齐，老文件没批量同步。

**完整审计**: 见 [docs/rfc/V2-VOCAB-DRIFT-AUDIT.md](V2-VOCAB-DRIFT-AUDIT.md)，6 类分类 + 文件级清单 + 清扫策略。

**修复**: 分 3 个子批次实施
- **#15.a (批次 2)**: ancestor → memory seat id 重命名 + skill rename + brief 自称统一 + planner SKILL roster 解耦（不再列死 reviewer/qa）
- **#15.b (批次 3)**: README + ARCHITECTURE + INSTALL.md + ITERM_TMUX_REFERENCE.md + 各 skill 的"六宫格"段全删
- **#15.c (M4)**: 全局 machine-memory-claude 删除 + PROJECT_BINDING.toml 废弃确认

**Owner**: builder-codex 实施 + planner-claude review + memory 做 vocab 词典 + 验收
**批次**: 批次 2 (#15.a) / 批次 3 (#15.b) / M4 (#15.c)

**验收**:
- `grep -r "ancestor" core/ scripts/` 只出现在：兼容性 alias、migration 工具、CHANGELOG/RFC/handoff
- `grep -r "六宫格\|six-pane" docs/ core/skills/` 返回 0 行
- `grep -r "machine-memory-claude" core/ scripts/` 每处都有 `# v1 LEGACY (M4 remove)` 注释

---

### #16 memory 汇报协议缺失 — 🟠 HIGH

**症状**: operator 实证 (2026-04-26 03:50) memory chat 是 flowing transcript，混着工具调用块、internal thinking、长 sed、receipt JSON；要滚 80+ 行才知道当前状态。

**根因**: memory 没有显式的汇报协议；现有 `clawseat-ancestor` skill 覆盖 Phase-A bootstrap，但 Phase-B（持续运营）的 reporting / dispatch / backlog ops 没规范化。

**修复**: 落地 [clawseat-memory-reporting skill](../../core/skills/clawseat-memory-reporting/SKILL.md) v1（已写）:
- L1 STATUS.md 持久状态（schema 见 [references/status-md-schema.md](../../core/skills/clawseat-memory-reporting/references/status-md-schema.md)）
- L2 chat 尾块 ≤ 5 行结构化
- L3 backlog detail 文件归属 + issue 模板
- L4 dispatch 1 行收据

**派工内容**:
- **memory 立即生效**: 自我规训按本协议汇报（不需 install team 介入）
- **批次 2 派 builder-codex**: 改 dispatch_task.py / agent_admin 自动 append STATUS.md dispatch log，避免 memory 手动维护出错
- **批次 2 派 planner-claude**: 把现存 `~/.agents/tasks/install/STATUS.md` 迁移到本 schema

**Owner**: memory（自我规训立即） + builder-codex（自动化）+ planner-claude（migration）
**批次**: 立即（memory 自律） / 批次 2（自动化 + migration）

**验收**:
- operator `cat ~/.agents/tasks/install/STATUS.md` ≤ 30s 知道当前状态
- memory chat 任意一次回复尾块完整
- 新 issue 发现后 ≤ 5min 出现在 backlog

---

### #17 install.sh Step 9.5 auto-send 不可靠 — 改 confirm-then-dispatch UX — 🟠 HIGH

**症状（2026-04-26 04:36 arena 实证）**:
- arena 安装期间 `auto_send_phase_a_kickoff` 卡 2:34，max_polls 走完都没成功 paste
- 根因可能：arena-memory 用 host oauth 复用 host login 直接 ready，不经过 OAuth 弹窗→关闭流程；send-and-verify 的 ready 检测画面不匹配
- arena-memory pane 长时间停在 Claude Code start screen（"Welcome back Yu!" + 空 ❯）
- 等 max_polls 到 fallback 到 banner 也得 3min，UX 差

**operator 提案（2026-04-26 04:38）**:
> 移除 auto-send 的逻辑，等用户确认项目-memory 就绪；由负责安装的 agent（install-memory）发送同时告诉用户如果失败可以手动复制粘贴 prompt

**修复设计**:
1. 删除 install.sh `auto_send_phase_a_kickoff()` + Step 9.5 整段
2. 改成：install.sh 跑完 Step 9（focus pane）后**直接退出**，把 kickoff prompt 写到 `~/.agents/tasks/<project>/patrol/handoffs/memory-kickoff.txt`
3. install.sh 末尾 banner 给 operator 3 个明确选项:
   ```
   ✔ Install complete. <project>-memory pane is ready.
   To start Phase-A, choose one:
     A) Existing install-memory will dispatch kickoff to <project>-memory:
        bash <path>/send-and-verify.sh --project <project> <project>-memory \
          "$(cat ~/.agents/tasks/<project>/patrol/handoffs/memory-kickoff.txt)"
     B) Manual paste — open <project>-memory pane, copy the prompt from:
        cat ~/.agents/tasks/<project>/patrol/handoffs/memory-kickoff.txt
        and paste into the Claude Code prompt
     C) install-memory dispatches automatically:
        say "dispatch arena kickoff" to install-memory in chat
   ```
4. 临时手动验证（arena 已用此模式）:
   ```bash
   bash send-and-verify.sh --project arena arena-memory "<kickoff text>"
   ```

**Owner**: builder-codex（删 auto_send + 改 banner） + memory（更新 brief 让新 memory 知道自己是被外部 dispatch 启动的）
**批次**: batch 2 后续（Package E 可顺手做，operator 拍）

**验收**:
- 新项目 install 完不再有 9.5 卡死 → install.sh 退出 ≤ 60s
- operator 看到清晰的 3 选项 banner
- 选项 A 通过 send-and-verify 一行即发
- 选项 B 真的能 cat 出可贴的纯文本 prompt（无 ANSI / 编码问题）

**关联**:
- 这个修法**取代** #2（auto_send 72s→180s 不再相关，整段删了）— #2 可标 superseded by #17
- 跟 #1 (brief render dynamic) 配合：brief 里描述 spawn worker 的 phase 不变，只是触发方式变 user-initiated

---

### #18 clawseat-ancestor SKILL/brief 缺 seat 失败诊断流程 — 🟠 HIGH

**症状（2026-04-26 04:55 arena 实证）**: arena-memory 把 builder 死亡误诊为 "401 Unauthorized"，反复 stop+start 没用。实际是 xcode.best 瞬时 disconnect，gpt-5.5 endpoint 完全 OK（curl 200）；arena-memory 没 cat codex-tui.log 就开始猜。

**根因**: SKILL 和 brief 都没规定"seat 死后做什么"的 canonical 步骤。memory 凭印象诊断 → 错指根因 → 错修。

**修复**: clawseat-ancestor SKILL.md + ancestor-brief.template.md 都加 §"Seat 失败诊断三步走"（强制顺序）:
```
1. cat <runtime>/codex-home/log/codex-tui.log | tail -30   # 看真实错误
2. curl -H "Authorization: Bearer $KEY" $BASE_URL/v1/responses ...  # 验证 endpoint
3. 只有前两步都正常才 stop+start
```
配合 #19 的 seat-diagnostic.sh 一键化。

**Owner**: memory (skill 文档) + builder-codex (brief template)
**批次**: Package P (插队批次 1.5)

**验收**: 新项目 memory 遇 seat 死，先跑 diagnostic 再行动；不再有 "凭直觉猜 401" 类型 RCA

---

### #19 seat-diagnostic.sh 一条命令诊断 — 🟡 MEDIUM

**症状（配合 #18）**: 即使 SKILL 写明"先看 log 再诊断"，memory 也得记住 4 个不同的 path/命令（codex-tui.log / claude TUI 没 log / curl 命令 / secrets path）。容易遗漏。

**修复**: 写 `core/scripts/seat-diagnostic.sh <project> <seat>` 一条命令打印:
1. tmux session alive? + 客户端数
2. 对应 tool 的 tui.log 最近 30 行（codex 走 codex-tui.log；gemini 走 gemini-cli.log；claude 走 ~/Library/Logs/Claude/claude.log）
3. 从 last-harness.toml 读 provider → curl /v1/models（如果是 API tool）→ HTTP code
4. 检查 secrets/<provider>/<seat>.env 存在 + 有 OPENAI_API_KEY/ANTHROPIC_API_KEY 字段

**Owner**: builder-codex
**批次**: Package P

**验收**: `bash seat-diagnostic.sh arena builder` 输出一屏总览，memory 30s 内定位根因

---

### #20 (预留新 issue 编号)

---

### #22 dispatch_task / 包 objective 缺显式 test_policy 字段 — ✅ DONE (c45f989)

**症状（2026-04-26 05:30 Package P1 实证）**: builder 完成 #17 实现后 blocked 在 `tests/test_install_isolation.py:486`（断言 auto-send 副作用），不敢动 test 因为 batch 2 objective 写过 "DON'T touch tests"。但 batch 2 是 vocab rename（test 用 v1 fixture，确实不许动），Package P 是功能重构（test 必须跟代码改）—— builder 把 batch 2 规则**静默继承**到 P 上下文，导致卡链。

**根因**: dispatch 协议没有 per-package 的 test policy 字段。builder 只能从前一个包猜，不同语义的包用同一规则会出错。

**修复**:
1. `dispatch_task.py` 加 `--test-policy` 必选参数:
   - `UPDATE` (功能改 → test 必须跟改)
   - `FREEZE` (vocab/rename → test 不动)
   - `EXTEND` (新功能 → 加 test 不删旧)
   - `N/A` (纯文档/配置)
2. memory 派包**强制填**；TODO.md 渲染时把 policy 列在最显眼位置
3. builder skill (`core/skills/builder/SKILL.md` 或 codex template) 写明：每个包的 test_policy 是 hard rule，不许跨包继承
4. 同时把"batch 2 DON'T touch tests"那种 batch 级规则改成 per-package 写

**Owner**: builder-codex（dispatch_task.py）+ planner-claude（review test_policy 取值）+ memory（更新 reporting skill 和 brief 强调 policy 字段重要性）
**批次**: 批次 3（不阻塞当前任务）

**验收**:
- `dispatch_task.py --help` 显示 `--test-policy {UPDATE,FREEZE,EXTEND,N/A}` 必选
- builder 收到的 TODO.md 头部明显写 `test_policy: <value>`
- 跨包不再静默继承 test 规则

**关联**:
- 是 Package P1 卡链的事后修复
- 跟 #16 reporting protocol 配合：memory chat 尾块 dispatches 区可以显示每个 active dispatch 的 test_policy

---

### #24 memory seat CWD 錯用 PROJECT_REPO_ROOT 而非 MEMORY_WORKSPACE — 🔴 BLOCKER

**症状 (2026-04-26 smoke test)**:
- testbed-v2-memory 在 clawseat-v2 worktree 啟動（--dir $PROJECT_REPO_ROOT）
- Claude Code 往上找到 /Users/your-user（cartooner/openclaw workspace 規則）
- memory seat 沒有 ClawSeat 身份 / 角色指示

**根因**: install.sh line 1897 `launch_seat` 傳 PROJECT_REPO_ROOT 而非 MEMORY_WORKSPACE；
MEMORY_WORKSPACE=$HOME/.agents/workspaces/$PROJECT/memory 有正確的 CLAUDE.md 但沒被用。

**修復**: line 1897 改 MEMORY_WORKSPACE，fix-24-memory-seat-cwd commit 中處理。

**Owner**: builder-codex（已修）

---

### #25 install.sh 默认 memory 模型改为 codex gpt-5.4-mini — 🟠 HIGH

**来源**: RFC-002 §2.2 + operator 2026-04-26 决策（轻量 model 跑 project-memory）

**当前**: install.sh 默认 memory seat 用 claude oauth + Anthropic（Opus 4.7）
**目标**: 默认 `--memory-tool codex --memory-model gpt-5.4-mini`；显式 override 可换回 claude opus

**修复**:
- `scripts/install.sh` parse_args 加 `--memory-tool` `--memory-model` flag
- `core/templates/retired-v2-starter.toml` 改 memory seat 默认 tool/model
- install.sh Step 3 select_provider 跳过 claude provider 选择（如果 --memory-tool=codex）

**Owner**: builder-codex
**批次**: batch 4 (M1.6)
**test_policy**: UPDATE

**验收**: `bash install.sh --project foo --template retired-v2-starter` 默认装 codex gpt-5.4-mini memory；现有项目 `--reinstall --memory-tool claude --memory-model claude-opus-4-7` 保持现状

**关联**: 跟 #1 brief 动态化协同

---

### #26 4 个新 skill 落地（memory v0.8 / koder v1 / privacy v1 / decision-escalation v1）— 🟠 HIGH

**来源**: RFC-002 §11 M1.6

**已写 draft (machine-memory commit, 见本批次)**:
- `core/skills/clawseat-decision-escalation/SKILL.md`
- `core/skills/clawseat-koder/SKILL.md`
- `core/skills/clawseat-privacy/SKILL.md`
- `core/schemas/decision-payload.schema.json`

**未做（install team 实施）**:
1. `clawseat-memory` v0.8 refresh: 现有 SKILL.md 还是 v0.7 ancestor 心智，需重写为 RFC-002 v2.1 架构（§4 决策三选一 / §9 隐私 pre-action / §10 patrol）
2. 5 个 seat skill 都加 `related_skills: [clawseat-decision-escalation, clawseat-privacy]`
3. `core/scripts/privacy-check.sh` 实现（详 clawseat-privacy §3）
4. install.sh 注册 4 个新 skill 软链到 `~/.agents/skills/`
5. commit pre-commit hook invoke privacy-check.sh
6. starter `~/.agents/memory/machine/privacy.md` 建文件

**Owner**: planner-claude（review skill content）+ builder-codex（实施 helper + hook + install.sh 注册）
**批次**: batch 4
**test_policy**: EXTEND

**验收**: 5 个 seat skill 都 reference 新 skill；privacy-check.sh 拒绝 staged file 含 sk-* 模式；4 个新 skill 启动时被 Claude Code / Codex CLI 加载

---

### #27 per-project patrol launchd plist 实现 — 🟡 MEDIUM (M2 范围)

**来源**: RFC-002 §10

**目标**: 每个项目自己的 launchd plist 定时维护 docs / 偏好 / backlog 健康。

**修复**:
- 写 `core/templates/patrol-plist.template`（参数化 PROJECT 名）
- install.sh 装项目时注册 plist 到 `~/Library/LaunchAgents/clawseat.<project>-memory.patrol.plist`
- uninstall 时删 plist
- patrol 脚本 `scripts/project-memory-patrol.sh <project>` 实现 §10 5 步动作

**Owner**: builder-codex
**批次**: M2（不阻塞 M1.6）
**test_policy**: EXTEND

**验收**: 装一个 testbed 项目，1 天后看 patrol log 有 5 步动作执行；unregister 项目，plist 自动消失；不重蹈 v1 clawseat-patrol 的盲跑

---

### #28 decision_payload 协议 runtime 落地 — 🟠 HIGH

**来源**: RFC-002 §6 + clawseat-decision-escalation skill

**目标**: planner / memory / koder 三方实施 payload schema 通信。

**修复**:
1. **planner 侧**: 当遇决策点写 payload + tmux-send memory（替代当前自由文本 escalation）
2. **memory 侧**: 收 payload 时按 §3 6 类判定路径；STATUS.md dispatch log 标 `decided locally / peer / escalated`
3. **koder 侧**: OpenClaw lark plugin 接 decision_payload，render Feishu card；接 button click + 文字回复，翻译为 prompt
4. `dispatch_task.py` 加 `--payload-file <path>` flag，自动 schema 校验
5. 写 `core/scripts/decision-broker.sh`：planner / memory 共用的 payload validation + tmux-send helper

**Owner**: builder-codex（schema validator + helper）+ planner-claude（review）+ koder（OpenClaw lark plugin，跨仓 PR）
**批次**: M1.6 后期（依赖 #26 skill 先 land）
**test_policy**: EXTEND

**验收**: planner 升级时写完整 payload schema 校验通过；memory 按 §3 路径走；koder Feishu card render manual smoke 通过；timeout 自动触发

---

### #29 memory-kickoff.txt → memory-kickoff.txt artifact rename — 🟡 MEDIUM (deferred)

**来源**: designer visual QA (pkg-visual-qa-designer-review) MEDIUM #2

**症状**: install.sh 生成的 artifact 文件名仍用 ancestor 词汇：
- `~/.agents/tasks/<project>/patrol/handoffs/memory-kickoff.txt`
- `~/.agents/tasks/<project>/patrol/handoffs/memory-bootstrap.md`
- CLAWSEAT_MEMORY_BRIEF env var

**缓解**: 这些文件名只影响文件系统可见性和 env var 名字，功能不受影响。
operator 已知晓，A' 决策时明确 defer（breaking change：现有项目的 kickoff.txt 路径在 OPERATOR-START-HERE 里硬编码）。

**修复时机**: 可以在 M2 期间或单独 micro-PR 处理。改法：
- install.sh `BRIEF_PATH` / `KICKOFF_PATH` 变量改为 memory-kickoff.txt / bootstrap-brief.md
- CLAWSEAT_MEMORY_BRIEF → CLAWSEAT_MEMORY_BRIEF (加 compat alias)
- OPERATOR-START-HERE 路径同步

**Owner**: builder-codex
**批次**: 自选时机（不阻塞 PR merge）

---

### #30 iterm_panes_driver tabs ensure-mode 假阳性 silent skip — 🟠 HIGH

**症状（2026-04-27 cartooner ↔ machine-memory 跨项目首测中暴露）**:
- `cartooner` 项目装好后，clawseat-memories 窗口缺 `cartooner` tab → operator 看不到 cartooner-memory（虽然 tmux session 活）
- 手动调 `iterm_panes_driver.py` payload `{"name": "cartooner", ...}` 期望补 tab
- driver 返回 `{"status": "ok", "tabs_created": 0, "tabs_skipped": 1}` —— silent skip
- 实际**没有**任何 tab 含 cartooner（osascript + Python iterm2 双重确认）
- 用 osascript `create tab + write text "tmux attach -t '=cartooner-memory'"` 直接创建 → 成功 attach

**实测 Python iterm2 看到的 tabs 元数据**（_window_title 命中 'clawseat-memories' 的窗口）:
```
tab 1: user.tab_name='arena',                  session.name='arena (tmux)'
tab 2: user.tab_name='install',                session.name='install (tmux)'
tab 3: user.tab_name=None,                     session.name='machine-memory-claude (tmux)'  # v1 ghost
```

osascript 还能看到第 4 个 tab（machine-memory-claude），Python iterm2 看不到 → osascript/Python 视图漂移依旧（参考之前 iTerm hang 事件）。

**根因（3 层嵌套）**:

1. **`_tab_name()` 检测顺序脆弱**: `user.tab_name` → `iterm2.get_tab_title()` → `session.name`
   - 中间步骤 `await tab.async_invoke_function("iterm2.get_tab_title()")` 在当前 iTerm SDK **总返回 RPCException**（实测），永远 fallback 到 session.name
   - 把 `"machine-memory-claude (tmux)"` 这种带 ` (tmux)` 后缀的 session.name 当 tab 名 → 命名匹配脆弱

2. **可能 race / stale state**: driver 返回 tabs_skipped=1，说明 existing_names 含 "cartooner"。可能来源:
   - 之前 cartooner install 在另一个 ghost iTerm window 设过 `user.tab_name='cartooner'`，driver 选错 window
   - matching_windows 多于 1，driver 选 [0] 错了
   - osascript-only-visible window 持有 stale `user.tab_name='cartooner'`，但 Python iterm2 看不到 → 不属于实际工作窗口

3. **silent skip 不反映真实状态**: driver 返回 status=ok 让调用方误以为成功，但 ensure 检测错误导致无操作 → 调用方（install.sh OR memory）继续往下走，operator 永远看不到新 memory tab

**修复方案候选**:

a. **加 cross-check**: ensure 时不只比 _tab_name，再 cross-check `current_session.async_get_variable('session.name')` 是否真的包含期望的 tmux session name (e.g. session.name 包含 `cartooner-memory` 才算匹配)
b. **iterm2.get_tab_title() RPCException 处理**: 探查 RPCException 根因（SDK 版本兼容？iTerm 配置？），如不能修就显式 ignore + 文档化
c. **matching_windows 多于 1 时 hard fail**: 不再 silent pick [0]，要求 caller 清理重复窗口（OR 提供 cleanup helper）
d. **status=warning when skipped**: 区分"创建成功 / 检测到已存在 / detect 失败 silent skip"，让调用方能区分
e. **osascript fallback path**: 如果 ensure-mode 检测不到 tab 但 osascript 能看到，用 osascript 直接 attach（绕开 Python iterm2 视图盲点）

**建议组合**: (a) + (c) + (d)
- (a) 修匹配脆弱性
- (c) 防 ghost window 误选
- (d) 让调用方能 detect false positive 重试

**Owner**: builder-codex（实施）+ planner-claude（review fix scope）+ designer-gemini（测多 ghost window 场景，模拟 osascript 残留 ghost）
**批次**: 批次 4.5 / micro-PR（不阻塞 batch 4 末尾包）
**test_policy**: UPDATE（功能改 + 测试要 cover 这个 false-positive 路径）

**验收**:
- repro test: 故意创建一个 ghost window 持 `user.tab_name=foo`，再 driver call ensure foo → 应该 detect 到 ghost OR 在主窗口正确创建（不要 silent skip）
- ensure 任意场景下 `tabs_created + tabs_skipped` 都反映真实最终状态
- 多 matching_windows 时报错而非 silent pick
- cartooner 实际 repro 成功修复（手动重 install cartooner 不需 osascript 辅助）

**关联**:
- 跟 #20 (osascript 频繁调用 hang) 同源: iTerm 视图层 osascript/Python 不一致
- 跟 #4 (memories tabs feature, commit 1233720) follow-up
- 跟 #6 (close+rebuild 改 ensure-tab) follow-up

---

### #31 v1 模板残留 + skill 注册双引擎不对称 — 🟠 HIGH

**症状（2026-04-27 cartooner-memory 实测）**: project-memory 角色定义不清晰，因为 3 处 v1 模板没被 v2 RFC-002 覆盖。

**3 处 gap**:

#### A. brief 模板没 vocab refresh

`core/templates/memory-bootstrap.template.md` 仍含:
- "你是 ClawSeat **始祖 CC**"（应 "project-memory"）
- "六宫格"（应 "workers + memories 双窗口"）
- "monitor grid: clawseat-cartooner"（应 `clawseat-cartooner-workers` + `clawseat-memories`）
- "machine-memory-claude" 引用（v1 已删）
- "grep `clawseat-ancestor/SKILL.md`"（已 rename 为 `clawseat-memory`）

**根因**: #15.b commit 1c1876c 标"vocab sweep across README/ARCHITECTURE/docs"，但 brief template 在 `core/templates/`，不在 `docs/`，**sweep 漏了**。

#### B. workspace 模板 generic specialist 心智

每个 memory 的 workspace 文件都是 v1 generic：
- `~/.agents/workspaces/{install,arena,cartooner}/memory/CLAUDE.md|GEMINI.md` 都写 "Specialist seat. Execute TODO.md and return to planner"
- RFC-002 §2.2 说 project-memory 是 L3 战术层 hub，**不是 specialist**，不该"return to planner"
- workspace 还含 v1 `WORKSPACE_CONTRACT.toml`（M4 才 deprecate，但 vocabularly 该改）

**根因**: workspace template 渲染逻辑用的是统一"specialist worker"模板，没区分 memory 角色。需要 memory 专属 workspace template。

#### C. skill 注册双引擎不对称

- `~/.agents/skills/` 只 symlink 了 3 个新 skill（decision-escalation, koder, privacy）
- **漏了 clawseat-memory v0.8** 本身
- Gemini 不读 `~/.agents/skills/`，它读 `~/.gemini/skills/` —— cartooner-memory 用 gemini，看不到任何 ClawSeat skill
- cartooner-memory 状态栏 "6 skills" 是 Gemini 自己默认的，跟 ClawSeat 无关

**根因**: #26 install_skill_symlinks 只覆盖 Claude Code path，没覆盖 Gemini / Codex path。

**修复方案**:

**A 修复**:
- core/templates/memory-bootstrap.template.md 全文重写（按 RFC-002 §1-§9 vocab）
- "始祖 CC" → "project-memory"; "六宫格" → "workers/memories 双窗口"; "machine-memory-claude" 删除引用
- skill path 引用全部 `clawseat-ancestor` → `clawseat-memory`

**B 修复**:
- 新建 `core/templates/workspace-memory.template.md.{claude,gemini}`（memory 专属，写 RFC-002 §2.2 角色定义）
- install.sh Step 5.5 / 5.7 渲染 memory workspace 时用新模板（替代 generic worker 模板）
- 各 memory workspace 的 GEMINI.md/CLAUDE.md 重新生成（migration script）

**C 修复**:
- `install_skill_symlinks` 加 clawseat-memory + clawseat-memory-reporting 到 symlink 列表
- 加 Gemini path: `~/.gemini/skills/<skill>` symlink 到 `core/skills/<skill>`
- 加 Codex path: 调研 codex 读 skill 的位置（如有）
- `core/scripts/install-skill-symlinks.sh` 检测当前 seat 用的 tool，按 tool 注册到对应 path

**Owner**: builder-codex（实施 3 修复）+ planner-claude（review brief 重写）+ designer-gemini（视觉对比新旧 brief）+ memory（写 workspace memory template draft）
**批次**: 批次 5（M1.6 收尾必修，否则 v2 多项目场景下 memory 角色定义全错）
**test_policy**: UPDATE（功能改 + 测试要 cover memory workspace 渲染走新模板）

**验收**:
- 装新项目: brief 顶部含 "project-memory"（无 "始祖 CC"），无 "六宫格"
- memory workspace CLAUDE.md/GEMINI.md 含 "L3 project-memory hub" 角色（无 "Specialist. return to planner"）
- `~/.agents/skills/` + `~/.gemini/skills/` 都有 5 个 ClawSeat skill 符号链接
- cartooner-memory 启动时 Gemini 加载 ClawSeat skills（状态栏 skill 数 ≥ 6 + ClawSeat）
- repro: 重装 cartooner，无需手动改任何 workspace 文件，memory 角色就清晰

**关联**:
- 根因之一是 #15.b sweep 范围漏 `core/templates/` —— 立完 #31 后建议复盘 #15.b 验收标准
- 跟 #26 (skill 注册) 增量补 Gemini/Codex path
- 跟 #5 (brief session check) 一起做 brief 模板重写

---

### #32 heartbeat / agent_admin spawn 假设 memory 是 claude — 🔴 BLOCKER for codex/gemini memory

**症状（2026-04-27 cartooner-memory 实测）**: cartooner-memory 跑 `agent_admin session start-engineer memory --project cartooner` 触发错误:
```
memory: heartbeat provisioning currently targets Claude sessions only
```

**影响**: #25 把 install.sh 默认 memory 改成 codex gpt-5.4-mini，但 spawn 链路（agent_admin session start-engineer）假设 memory 必须是 claude。结果 codex memory 无法被 agent_admin re-spawn / re-bind / heartbeat 健康检查。

**根因**: `agent_admin_session.py` / `heartbeat_config.py` 类的 spawn 路径只 implement claude 的 heartbeat / OAuth check / sandbox seed，没 cover codex (chatgpt auth) / gemini (oauth/google) memory 场景。

**修复**:
1. grep `agent_admin*.py heartbeat*.py` 找所有 "claude only" 假设，分两类：
   - 真的只能 claude（如 OAuth token 类） → 文档化 + 在 codex/gemini memory 场景 graceful skip + warn（不抛错）
   - 应该 generic（如 heartbeat 心跳）→ 拓展到所有 tool
2. `agent_admin session start-engineer memory` 必须支持 3 tool（claude/codex/gemini），不论 auth 模式
3. 为 codex memory 加 sandbox/secret seed path
4. 测试: 装 cartooner（codex memory）→ agent_admin start-engineer 成功 spawn 4 seat；装 install（claude memory）保持现状不破

**Owner**: builder-codex（实施 spawn 路径泛化）+ planner-claude（review heartbeat 协议设计）+ 我（machine-memory，review codex/gemini memory 的 sandbox 隔离要求）
**批次**: 紧急 micro-PR，**M1.6 阻塞**（不修，#25 codex 默认形同虚设；任何 codex memory 项目都跑不通 Phase-A B4）
**test_policy**: UPDATE（功能改 + 必须 cover claude/codex/gemini 三 tool memory spawn 测试）

**验收**:
- `agent_admin session start-engineer memory --project cartooner`（codex memory）成功 spawn，无 "heartbeat" error
- 装 cartooner 全程 Phase-A B0-B7 走通，4 seat 全 alive
- 不破坏现有 install/arena（claude memory）

**关联**:
- 是 #25 (codex gpt-5.4-mini 默认) 的隐藏依赖暴露
- 跟 #31 一起做（brief vocab + heartbeat 都是 multi-engine 兼容性问题）
- 跟 #19 (seat-diagnostic.sh) 跨工具诊断同源

---

### #33 brief 不强制 project.toml seat_overrides 权威 → planner provider 幻觉 — 🟠 HIGH

**症状（2026-04-27 cartooner-memory 实测）**: cartooner-memory B0 写出的 memory-provider-decision.md 含:
```
planner: gemini / oauth / google
```
但 project.toml seat_overrides.planner 明确:
```
tool = "claude"
auth_mode = "oauth"
provider = "anthropic"
```

**根因**: brief B0.0.1 让 memory "读 machine 层 credentials 综合做 provider 决策"。codex memory 看到 machine credentials.json 含 `gemini google_accounts.json` + `OPENAI_API_KEY`，**脑补**出 planner=gemini（因为 gemini 有 OAuth 资源），无视 project.toml 的明确 override。

brief 没显式说"project.toml seat_overrides 是 SSOT，不许覆盖"，导致 LLM 当作"参考资料"灵活解读。

**修复**:
1. brief B0 / B3.5 加强制语句:
   ```
   project.toml [seat_overrides.<seat>] 是 SSOT。
   memory 必须按 seat_overrides 的 tool/auth/provider 字面量 spawn，
   不许根据 machine credentials 推断或 override。
   如果 seat_overrides 不存在某 seat，才能 fallback 到 template default。
   ```
2. memory-provider-decision.md 模板加显式字段:
   ```
   ## project.toml authority check
   - Source: ~/.agents/projects/<project>/project.toml
   - Override count: <N>
   - Decisions match overrides: yes / no
   ```
   让 memory 必须显式 ack 自己读了 project.toml.
3. `agent_admin session start-engineer` 收到与 project.toml 不符的 spawn 请求时 **hard fail**（不许 spawn 与 project.toml 不一致的 seat），加 `--accept-override` flag 仅供 operator override

**Owner**: builder-codex（实施 hard fail）+ planner-claude（review brief 文案）+ memory（写 brief 加强段 draft）
**批次**: 紧急 micro-PR（跟 #31 brief refresh 合并最自然）
**test_policy**: UPDATE

**验收**:
- 装 cartooner（project.toml planner=claude） → memory memory-provider-decision.md 必须写 planner=claude
- agent_admin 拒绝 spawn 跟 project.toml 不一致的 seat（除非 --accept-override）
- brief grep 显示 "project.toml seat_overrides 是 SSOT" 字样

**关联**:
- 跟 #31 brief refresh 一起改
- 跟 #22 (test_policy) 同类: 都是把"隐性约定"显式化

---

### #34 codex gpt-5.4-mini skill context budget 超限 — 🟡 MEDIUM

**症状（2026-04-27 cartooner-memory 启动）**: codex 状态栏 warn:
```
⚠ Exceeded skills context budget of 2%. Loaded skill descriptions were truncated by an average of 150 characters per skill.
```

**根因**: codex gpt-5.4-mini context window 比 claude opus 小，加载 6 个 skill 的 description 已经超过 codex 的 2% startup budget。每个 skill description 平均被截断 150 字。

**影响**: 关键 skill 内容（特别是新 skill: clawseat-decision-escalation / clawseat-koder / clawseat-privacy）被截断，memory 看到的协议片段不完整 → 决策可能漂移。

**修复方案候选**:
a. **缩 skill description**: 把每个 skill 的 description 字段精简到 < 150 字符（保留 SKILL.md body 完整）
b. **按需加载**: codex 启动时只 reference skill 名，body 通过 codex grep tool 按需读
c. **memory tier 自适应**: 检测到 codex/gemini 等小 context model 时只注册必需的 3 个 skill，省略 OpenClaw/lark 类
d. **拆 skill**: 把 reporting / decision / privacy 合并成一个 "clawseat-memory-protocol" 元 skill

**建议组合**: a + c
- a 治标（缩 description）
- c 治本（按 model tier 注册 skill 集）

**Owner**: builder-codex（实施 skill description 缩 + tier-based registration）+ 我 machine-memory（review skill description rewrites）
**批次**: M1.6 后期（不阻塞，warn 不是 error）
**test_policy**: UPDATE

**验收**:
- codex gpt-5.4-mini memory 启动无 "Exceeded skills context budget" warn
- skill 内容仍能被 memory 正确 reference

---

### #35 (预留新 issue 编号)

---

## 修复批次规划

### 批次 0（ancestor 立刻自修, 不等 install team）— 🔴 BLOCKER

- **#10** workers_payload planner pane 错用 tmux attach → 改 wait-for-seat（ancestor 自己 fix, 是新引入 bug）

### 批次 1（4 seat 齐后立刻派）— 🟠 HIGH

- #1 brief 模板动态化
- #2 auto-send 窗口扩展
- #4 memories 窗口 tabs 改造
- #5 brief session check 修复
- #11 reseed-pane iterm2 API send_text 失效（改 AppleScript 或加 activate）
- #12 recover-grid.sh + 辅助脚本 PRIMARY_SEAT_ID 重构漏改
- #13 agent_admin window open-grid 仍用 v1 单窗 (operator 实证: recover-grid.sh 跑出 v1 拓扑)

### 批次 2（批次 1 验收通过后）— 🟡

- #3 banner 文案
- #6 memories 增量 rebuild

### 批次 3（M2 启动）— 🟢 LOW + M2

- #7 projects.json 正式注册表
- #8 watchdog 集群

### 批次 4（M4）— 清扫

- #9 删除 machine-memory-claude

---

## Operator 实时反馈记录区

> Operator 持续报告的新问题在这里 append，附时间戳 + 上下文。

### 2026-04-26 02:00 — memories 窗口应用 tabs 而非 panes

→ 已建为 issue #4（HIGH）

### 2026-04-26 02:05 — install-memory 报 ARCH-VIOLATION（brief assert install-ancestor 存在）

→ 已建为 issue #5（MEDIUM）。临时决策: ancestor 已发 "proceed" 让 memory 把 brief assertion 视为 stale 继续 Phase-A。

### 2026-04-26 02:25 — install-memory 报 3 个根因（在 phase-a-decisions 之前先告诉 operator）

1. iTerm clawseat-install-workers 创建时 planner pane 没启动 wait-for-seat（builder/designer 启动了，planner 漏了）→ 已建为 #10 BLOCKER
2. agent_admin window reseed-pane 走 iterm2 API 路径有 bug：返回成功但 send_text 序列没真正写入空闲 zsh shell。直接用 iTerm AppleScript write text 才生效 → 已建为 #11 HIGH
3. 这个 bug + 所有 recover-grid.sh / grid-recovery 路径硬编码 install-ancestor 是 v2 minimal 的两个已知 stale 点 → 已建为 #12 HIGH

### 2026-04-26 03:00 — operator 让 ancestor 跑 recover-grid.sh install 救回 workers 视图

**实证发现**: recover-grid.sh + agent_admin window open-grid 走 v1 grid_payload 单窗口路径，与 install.sh main() 已实现的 v2 双窗口拓扑不一致。结果 install-memory 被 attach 了 2 次（v1 风格 clawseat-install + v2 风格 clawseat-memories）→ 已建为 #13 HIGH

---
