# Harness Startup Notes

当 `koder` 以 harness TUI 方式运行，且使用全新的隔离 `Claude Code CLI`
runtime 时，第一次启动可能不是“自动进入可用状态”，而是先进入首启交互。

这个现象已经在至少两种 API provider 上复现：

- `minimax`
- `xcode-best`

已确认的首启交互至少包括：

- `Bypass Permissions mode` 确认
- 主题选择（`/theme` onboarding）

重要判断：

- 如果新窗口一度出现又消失，不要先判定为 auth/provider/session 闪退
- 先检查是否是首启交互未完成导致的退出或卡住
- 这是新的 harness runtime 初始化过程，不是普通任务链异常
- `session = running` 也不等于 `seat = ready`
- 对 Claude harness，`running` 可能只是代表 tmux 还活着，但 TUI 仍停在 onboarding
- 不要把 `start-engineer` 误当成“恢复旧 Claude 会话”；它更接近 fresh live session

标准处理顺序：

1. 启动 session
2. 打开前台 TUI 窗口
3. 观察是否进入首启交互
4. 如有交互，由用户或当前操作者先完成 onboarding
5. onboarding 完成后，再检查 session 是否稳定驻留
6. 让该 seat 重读生成好的 workspace guide 与 `WORKSPACE_CONTRACT.toml`
7. 只有看到正常输入提示符，并确认 seat 已重读合同，才把该 harness seat 视为 ready

如果一个 Claude seat 以前是正常工作的，后来只是 live pane 掉了，
优先走恢复流程而不是 fresh start：

1. 确认原 workspace 仍在
2. 确认原 Claude runtime home / `XDG_*` 目录仍在
3. 确认 `.claude/history.jsonl` 或 `.claude/projects/.../<session-id>.jsonl` 仍在
4. 用原 workspace + 原 runtime home + 原 Claude session id 恢复
5. 只有恢复失败，才使用 `start-engineer`

经验教训：

- 对 Claude，会话记忆不只在 workspace
- 还强依赖同一份 runtime `HOME` / `XDG_*`
- 如果脱离原 runtime home 启动，即使 OAuth token 还在，也可能重新掉进
  trust / onboarding / login 流

复核方式：

- `python3 {CLAWSEAT_ROOT}/core/scripts/agent_admin.py show-engineer <engineer> --project <project>`
- `tmux capture-pane -pt <session>:0.0`
