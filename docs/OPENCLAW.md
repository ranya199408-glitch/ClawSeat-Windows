# OpenClaw × ClawSeat

> ClawSeat 不是一个独立 agent 框架。它是 [OpenClaw](https://github.com/openclaw/openclaw)
> 的本地研发前台——把 OpenClaw 的 agent 控制面整合进你 Mac 上 workers/memories iTerm 窗口的那一层。
> 要理解 ClawSeat，先理解 OpenClaw。

## OpenClaw 是什么

OpenClaw 是一个跑在你自己机器上的**多通道个人 AI 助手控制面**。MIT 开源，
默认绑 `127.0.0.1:18789`。一个 Gateway daemon 负责：

- **通道接入**——Feishu / WhatsApp / Telegram / Slack / Discord / iMessage /
  WeChat / Matrix 等 20+ 消息通道，用户在哪发消息，agent 就能在哪回
- **Agent 进程编排**——每个 agent 是独立的 Node.js 进程，通过 ACP（Agent
  Client Protocol）经 WebSocket 和 Gateway 通信，互不干扰、独立 memory
- **插件系统**——101 bundled extensions + [ClawHub](https://clawhub.ai) 市场，
  `openclaw plugins install <name>` 一行装完
- **心跳驱动**——agent 不只被动回复，心跳可按分钟粒度唤醒它主动行动
- **Delegate 架构**——agent 有自己的身份，能"代表"人发消息，规模化到团队

**这意味着什么**：OpenClaw 本身就是一个完整的本地 AI 生态，有 agent、通道、
内存、插件市场。ClawSeat 不从零造——它借 OpenClaw 的基础设施，在上面搭
ClawSeat 特有的 4-seat 研发工作流。

## ClawSeat 借用 OpenClaw 的五样东西

### 1. ACP Agent 进程模型（最核心）

OpenClaw 的 agent 通过 `openclaw acp` CLI 起一个独立 Node.js 进程。agent
和 Gateway 之间走 ndJSON stream + WebSocket（见 OpenClaw `src/acp/server.ts`）。

ClawSeat 的 4 个 seat——memory、planner、builder、designer
——每个都可映射到一个 OpenClaw agent 身份。seat 崩了，agent 身份还在；
换 provider（Claude → Codex → Gemini），身份保留。

### 2. Feishu 通道桥接

OpenClaw 的 `openclaw-lark` 插件（Feishu 官方通道）已经把 webhook、thread
binding、用户/机器人身份做好了。ClawSeat 直接用：

- `PROJECT_BINDING.toml` 里 `feishu_group_id` 绑 Feishu 群
- `feishu_sender_mode = "bot"` 或 `"user"`（代表机器人 / 代表操作员发）
- `feishu_external = false` 控制是否接受外部群消息

不需要在 ClawSeat 侧实现 Feishu SDK。ClawSeat 只管"**什么时候**该发 Feishu"，
**怎么发**是 OpenClaw 的事。

### 3. 心跳调度（Heartbeat）

OpenClaw 的 `src/infra/heartbeat-runner.ts` 按配置的 cadence（5min / 10min /
30min / 1h）发 `[HEARTBEAT_TICK project=X ts=T]` 到 Feishu 群。这就是
ClawSeat 的 `core/scripts/heartbeat_beacon.sh` + 对应 launchd plist 做的事：

- 唤醒休眠的 Feishu 侧 koder agent
- 触发 memory 的 Phase-B 稳态巡检
- 让远程用户通过 Feishu 打招呼时 agent 不是"下线"状态

配置：`~/.agents/heartbeat/<project>.toml`。关闭就把 `enabled = false`。

### 4. Koder Overlay — ClawSeat 的反向信道

koder 是**一个 OpenClaw agent 被 ClawSeat 重新身份化**——从"通用 agent"
变成"ClawSeat 本项目的 Feishu 前台代理"。

流程（`scripts/apply-koder-overlay.sh`）：

1. 选一个现有的 OpenClaw agent（比如 `yu`）
2. 重写它的 IDENTITY / SOUL / TOOLS / MEMORY / AGENTS / CONTRACT 文件，
   让它知道自己"受 ClawSeat 项目 `<X>` 委托"
3. 绑定到 `PROJECT_BINDING.toml::openclaw_koder_agent` 字段（运行时通过 `binding.extras.openclaw_frontstage_tenant` 读取）
4. Feishu 群里 @它 → 它透过 OpenClaw Gateway + tmux send-keys 转给本地 seat
   → 本地 seat 回复 → koder 把结果转回 Feishu 群

**koder 不是 ClawSeat 的 seat**。workers/memories 窗口里看不见它。它活在 Feishu 和
OpenClaw 侧，扮演"远程遥控器"的角色。

### 5. state.db 事件总线

OpenClaw 的 `~/.openclaw/state.db`（SQLite WAL 模式）是一个事件账本。
ClawSeat 的 `core/scripts/feishu_announcer.py` + `events_watcher.py` 挂在
这上面：

- 任务完成写一条 `task.completed` 事件
- seat 卡住写 `seat.blocked_on_modal`
- 上下文接近爆写 `seat.context_near_limit`
- 链关闭写 `chain.closeout`

事件被 `fingerprint(sha1(project|task_id|kind|source|target)[:16])` 去重，
确保同一个事件 Feishu 不会被推多次。

## 配置 ClawSeat ↔ OpenClaw 的契合点

### `PROJECT_BINDING.toml`（v3 schema）

ClawSeat 每个项目的单文件 SSOT，住在 `~/.agents/tasks/<project>/PROJECT_BINDING.toml`：

```toml
version = 3
project = "myproject"
feishu_group_id = "<FEISHU_GROUP_ID>"
feishu_group_name = ""
feishu_external = false
feishu_sender_app_id = "<FEISHU_APP_ID>"
feishu_sender_mode = "bot"              # 或 "user"
openclaw_koder_agent = "koder"          # 绑 OpenClaw 哪个 agent 做反向信道
tools_isolation = "shared-real-home"    # 或 "per-project"
require_mention = true                  # Feishu 是否要求 @ 才响应
```

### OpenClaw 那边需要就位的东西

ClawSeat 安装时**不会**自动装 OpenClaw。你需要先：

1. `~/.openclaw/machine/openclaw.json` 存在（OpenClaw Gateway 配置）
2. 至少有一个 OpenClaw agent 注册在 `~/.openclaw/agents/`
3. `openclaw-lark` 插件已装（`openclaw plugins list | grep lark`）
4. Feishu 群 webhook 已绑到 OpenClaw

不装 OpenClaw 也能跑 ClawSeat——workers/memories iTerm 窗口 + 本地 seats 全在。只是丢了
Feishu 通知、koder 反向信道、心跳唤醒这些功能。`CLAWSEAT_FEISHU_ENABLED=0`
环境变量可以明确关掉这块。

## 为什么是 OpenClaw 不是别的

- **MIT 开源，本地跑**——没有云依赖、没有 SaaS 订阅
- **Chinese-first**——Feishu 原生、中文社区活跃
- **协议层完整**——ACP agent 模型、插件 SDK、市场、心跳、delegate 架构都有，
  不需要我们自己造
- **开放可审计**——你能读它的每一行，我们也能

ClawSeat 的决定：**不做 OpenClaw 做得好的事**。通道、agent 进程、插件——
OpenClaw 负责。ClawSeat 负责 4-seat 研发工作流、dispatch 协议、
iTerm workers/memories 可视化、gstack skill 注入。

## 深入

- OpenClaw 文档：[docs.openclaw.ai](https://docs.openclaw.ai)
- OpenClaw 源码：[github.com/openclaw/openclaw](https://github.com/openclaw/openclaw)
- ClawHub 插件市场：[clawhub.ai](https://clawhub.ai)
- ClawSeat 架构：[`docs/ARCHITECTURE.md`](ARCHITECTURE.md)
- gstack 集成：[`docs/GSTACK.md`](GSTACK.md)
