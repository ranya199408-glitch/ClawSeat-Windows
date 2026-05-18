# Memory Operations Policy

Operational guardrails formerly embedded in `clawseat-memory` SKILL live here so
the seat SKILL can stay identity/boundary-only.

### 5.y · Feishu auth 状态决策树

| user_valid | bot_valid | 正确响应 |
| yes | no | send_delegation_report.py --as user |
| no | yes | send_delegation_report.py --as bot |
| mixed | mixed | feishu_sender_mode = "auto"; feishu_sender_app_id; openclaw_koder_agent |

### 5.1 memory 交互工具（直接脚本，不走 tmux）

Use `${CLAWSEAT_ROOT}/core/skills/memory-oracle/scripts/query_memory.py` and
`${CLAWSEAT_ROOT}/core/skills/memory-oracle/scripts/memory_write.py`; examples
include `--search "feishu"`, `--content-file /tmp/${PROJECT_NAME}-phase-a-decision.md`,
and `query_memory.py --ask`. 不要把 `tmux send-keys` 用在 project memory seat 上。

### 5.2 跨 seat 文本通讯（canonical）

Use `bash ${CLAWSEAT_ROOT}/core/shell-scripts/send-and-verify.sh`; red flag:
你自己 tmux send-keys 给 planner/builder/patrol 发消息. Patrol automation is opt-in via
`--enable-auto-patrol`.

### 5.3 dispatch diagnostics

Use `agent_admin.py project show ${PROJECT_NAME}`. For roster preflight import
`from _common import load_profile`, then read `profile_obj.seats`; this avoids
raw TOML underreporting in `dynamic_roster` projects.

### 5.x · Feishu via lark-cli（canonical 命令）

Commands: `lark-cli auth status`, `lark-cli auth status --as user`,
`lark-cli auth status --as bot`, `lark-cli im +chat-search`,
`lark-cli im +messages-send`, `send_delegation_report.py`, `--as auto`.
Keep `lark-cli app / OpenClaw agent app 不混`; OpenClaw koder overlay 目标;
`feishu_sender_app_id`; `openclaw_koder_agent`.

### Feishu diagnostics

飞书两层配置（非 @ 响应必需）: Layer 1, Layer 2, 只响应 `@` 消息,
完全不响应, 部分群不响应. Before diagnosis verify `real_user_home()`,
`shell HOME: $HOME`, `session reseed-sandbox --project <name> --all`; 未跑这个前置核验就开始下结论.
Do not debug with 手动 ln -s <sandbox>/.lark-cli or `HOME=<sandbox> lark-cli auth login`.

### Pane ↔ Seat 映射（不要靠显示名判断）

Use `user.seat_id` and `list-panes`.

### B3.5.0-bootstrap-preflight

Use `agent_admin project show ${PROJECT_NAME}`, then bootstrap + project use for
smoke01 / pre-SPAWN-049 legacy project. ### 6.5 L2/L3 Pyramid 边界;
ARCH-CLARITY-047 §3z.

### 9.1 Canonical 操作守则（R13 meta-rule）

Red flags: 凭训练数据拼 CLI, sudo, pip install, brew install, 试旧版 API,
start-identity, clawseat init, clawseat-cli.

| "我猜命令名是 ..." / 凭训练数据拼 CLI | 必须先查 Common Operations Cookbook / SKILL.md |
| "我先 sudo / pip install / brew install ..." | 禁止改宿主环境 |
| "试旧版 API（start-identity / clawseat init / clawseat-cli ...）" | 这些是 v0.5/v0.6/v0.8 名字，不是 canonical |

## 11. 识别 operator 错误指引 + 拒绝模板

ARCH_VIOLATION: 直接调 launcher，不走 agent_admin; tmux send-keys 给 memory;
operator-override; planner stop-hook.

### Brief drift 自检

Run `bash ${CLAWSEAT_ROOT}/scripts/memory-brief-mtime-check.sh`; handle
`BRIEF_DRIFT_DETECTED`; Brief immutability means no hot-reload.

### memory_query table

| Token | memory_query |
| `B0-memory-query` | yes |
| `B2.5-bootstrap-tenants` | yes |
| `B3.5-clarify-providers` | yes |
| `B1-read-brief` | no |

### Seat TUI 生命周期（强制理解）

`wait-for-seat.sh` 自动 re-attach; seat 重启 自动恢复. 不要手动 tmux attach; 禁止 tmux attach.
Use `open-grid --recover`.

### Window operations

Use `tmux list-panes -t '=${PRIMARY_SESSION_NAME}'`; implementation may use
`osascript` and `iterm_panes_driver.py`.

## Official Documentation Gate

External integrations require KB evidence under
`~/.agents/memory/projects/<project>/findings/`: Package name + version + CLI binary path,
plus Inference boundary.
