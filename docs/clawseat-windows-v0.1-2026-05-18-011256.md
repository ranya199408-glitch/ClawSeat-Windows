# ClawSeat Windows v0.1

**时间：** 2026-05-18 01:12:56 +08:00

## 今日目标

把 `<CLAWSEAT_ROOT>` 调整成 Windows 可用版本，并尽量贴近原版 ClawSeat 的运行方式：Windows 只负责入口和显示，真正运行环境放在 WSL Ubuntu 里。

## 最终架构

- **PowerShell**：Windows 入口脚本，负责安装、检测、启动。
- **WSL Ubuntu**：实际 runtime，运行 bash、Python、tmux、Claude Code 等。
- **tmux**：唯一的 seat 会话承载和任务传递层。
- **send-and-verify.sh**：唯一的任务/消息传输方式。
- **WezTerm**：只做窗口显示层，类似 macOS 版本里的 iTerm，不负责注入任务。
- **MiniMax API**：用于 Claude API seat，默认模型为 `MiniMax-M2.7-highspeed`。

## 已完成内容

### 1. Windows WSL-first 支持脚本

创建并完善了 Windows 入口相关脚本：

- `scripts/windows-support.ps1`
- `scripts/install-windows.ps1`
- `scripts/launch-windows.ps1`
- `scripts/smoke-windows-tmux.ps1`

关键能力：

- Windows 路径转换为 WSL 路径。
- PowerShell 调用 WSL bash。
- 检测 WSL、WezTerm、bash、python3、git、tmux 等依赖。
- Windows installer 在 WSL 内 bootstrap 项目状态。
- Windows launcher 在 WSL 内启动 seat，再用 WezTerm 显示 tmux session。

### 2. WezTerm 单窗口三 pane

将原来的多窗口显示改为一个 WezTerm 窗口内三 pane：

- planner
- builder
- reviewer

实现方式：

- 使用 `wezterm-gui.exe` 打开 GUI 窗口，避免额外 `wezterm.exe` 包装窗口。
- 使用 `wezterm.exe cli --prefer-mux split-pane` 创建 pane。
- 使用 PowerShell `-EncodedCommand` 避免路径、空格、中文目录和引号问题。

### 3. 修复 WezTerm 配置兼容问题

修复了本机和模板里的旧配置字段，避免 WezTerm 启动时报错。

移除的问题字段包括：

- `title_font_size`
- `format-window-title`
- `pane:get_title`
- `clawseat_enabled`

同时更新了：

- `scripts/wezterm_config_template.lua`
- `%USERPROFILE%\.config\wezterm\wezterm.lua`

### 4. 防止 installer 覆盖用户 WezTerm 配置

`install-windows.ps1` 现在写入 `wezterm.lua` 前会先备份已有配置：

```powershell
$configPath.<timestamp>.bak
```

这样以后重新安装不会直接丢失用户原来的 WezTerm 配置。

### 5. MiniMax API seat 配置

修复了 Claude Code 显示 `Not logged in · Please run /login` 的问题。

原因：MiniMax 走 Claude API 兼容接口时，需要使用：

- `ANTHROPIC_AUTH_TOKEN`
- `ANTHROPIC_BASE_URL`

不是空的 `ANTHROPIC_API_KEY`。

已直接配置 WSL 内相关 secret 文件，并保持密钥不输出、不写入文档。

### 6. installer 默认覆盖 planner / builder / reviewer / patrol

更新 installer，使新项目默认把以下 seat 配为 Claude + MiniMax API：

- planner
- builder
- reviewer
- patrol

避免 builder 保持 Codex OAuth、reviewer 保持 Anthropic OAuth 导致 Windows 端需要额外登录。

### 7. 创建并启动测试项目 `pbr`

创建并调整了 `pbr` 项目，用于验证三 seat：

- `pbr-planner-claude`
- `pbr-builder-claude`
- `pbr-reviewer-claude`

最终成功打开一个 WezTerm 窗口，显示 planner / builder / reviewer 三个 pane。

### 8. smoke 验证通过

对 `pbr` 的三席执行了 tmux smoke：

```text
Smoke probe delivered to planner: SENT: pbr-planner-claude
Smoke probe delivered to builder: SENT: pbr-builder-claude
Smoke probe delivered to reviewer: SENT: pbr-reviewer-claude
ClawSeat Windows tmux smoke complete for project 'pbr'.
```

说明任务传递链路仍然走 WSL/tmux/send-and-verify，而不是 WezTerm 文本注入。

### 9. 测试与审查

新增和更新了 Windows 支持脚本测试：

- WezTerm 模板不包含不兼容字段。
- installer 默认覆盖 API seat 到 MiniMax。
- installer 写 WezTerm 配置前会备份已有文件。
- launcher 使用一个 WezTerm 窗口和 split pane。
- smoke 脚本通过 WSL/tmux 发送验证消息。

执行过的重点验证：

- 针对性 Python 回归测试通过。
- PowerShell 脚本语法检查通过。
- `pbr` 三 seat smoke 通过。
- code-reviewer 审查通过，无 CRITICAL/HIGH 问题。

## 当前可用方式

### 安装/初始化项目

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<CLAWSEAT_ROOT>" -Project pbr -Template clawseat-engineering -Provider minimax -AllApiProvider minimax -MemoryTool claude -MemoryModel MiniMax-M2.7-highspeed
```

### 启动项目窗口

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<CLAWSEAT_ROOT>" -Project pbr -NoReset
```

### smoke 验证三席

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '<CLAWSEAT_ROOT>' -Project pbr -Seats planner,builder,reviewer"
```

## 已知问题

1. Windows 下直接跑完整 pytest 会因为 `tests/conftest.py` 引入 POSIX-only `fcntl` 失败。
   - 当前 workaround：用直接 import 的方式跑 Windows 相关测试函数。
   - 后续应把 `fcntl` 依赖隔离或做平台兼容。

2. WezTerm 旧 mux socket 有时会残留。
   - 现象：`wezterm cli list` 可能报 socket 连接失败。
   - 当前 launcher 仍能通过 GUI start 打开窗口。

3. `recover-grid` 有 warning。
   - 当前不阻塞 seat 启动和 smoke。
   - 后续可单独检查 `<HOME>/.clawseat/.agent/task-watch/grid-recovery.log`。

4. `pbr` 是今天用于验证的测试项目。
   - 后续如果要正式使用，可以继续沿用，也可以重新创建一个正式项目名。

## 安全注意

- 今天没有把真实 API key 写入文档。
- secret 文件只在本机 WSL 内配置。
- 不使用 WezTerm `send-text` 做任务注入。
- 不使用 pane 文本注入传任务。
- 不提交代码，除非用户明确要求。

## v0.1 结论

ClawSeat Windows v0.1 已达到可用状态：

- Windows 可启动。
- WSL runtime 可工作。
- WezTerm 可显示一个窗口三 pane。
- planner / builder / reviewer 三席可启动。
- MiniMax Claude API 登录状态正常。
- tmux smoke 传输验证通过。

下一步建议是整理完整 pytest 的 Windows 兼容问题，并把 `pbr` 之外的正式项目流程再跑一遍。