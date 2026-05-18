# iTerm + tmux 操作基线（ClawSeat）

## 1. 资料盘点（本地）

### A 级：主控（优先）
- `docs/INSTALL.md`（高）  
  - v0.7 安装/重入 playbook、`scripts/install.sh` 主链路、`tmux` 与权限故障修复文案。
- `core/scripts/agent_admin_window.py`（高）  
  - iTerm 打开/重连命令、`env -u TMUX`、重试、失败即停、监控布局回滚。
- `core/shell-scripts/send-and-verify.sh`（高）  
  - `tmux` 二进制发现、发送前后 capture、明确失败码（`TMUX_MISSING`、`CAPTURE_*`、`RETRY_*`）。
- `adapters/harness/tmux-cli/adapter.py`（高）  
  - `send-and-verify` 默认优先、失败原因可读化、`tmux` 执行器重试+超时。
- `core/scripts/agent_admin_session.py`（高）  
  - 会话启动/重建校验、半成品会话回滚、启动失败上下文（窗口状态与 pane 快照）。

### B 级：流程说明（参考）
- `core/scripts/agent_admin_workspace.py`（中）  
  - 明确“优先 send-and-verify、send-keys 属降级路径”。
- `core/skills/gstack-harness/references/chain-protocol.md`（中）  
  - 链路契约与默认策略说明。
- `docs/ARCHITECTURE.md`（中）  
  - tmux/iTerm 在架构中的角色定位。

### 本地可信度小结
- 代码文件：可信度高（可执行逻辑为唯一真相）。
- 文档：中高（需结合实际命令输出做回归验证）。

## 2. iTerm + tmux 外部实践对标（官方/社区）

## 2.1 结论先行
与官方实践没有明显冲突；当前实现与 iTerm 官方脚本约束与 tmux 的标准命令模型基本一致。  
主要差异在于：我们做了“发送后可验证 + 重试”这层工程补强，这是 `tmux` 本体未强制但非常实用的可靠性增强。

### 对标矩阵

| 项目 | 本地实现 | 外部实践 | 差距 |
|---|---|---|---|
| iTerm AppleScript 打开窗口/写入 | `create window with default profile` + `write text` | iTerm 官方文档的 `create window` 与 `write text`/`set current session` 风格一致。[官方脚本文档](https://iterm2.com/3.3/documentation-scripting.html) | 一致。保留旧名 `iTerm` 和 `iTerm2` 的双应用名兼容是合理增强。 |
| 会话 attach 命令 | `env -u TMUX tmux attach -t ...` | `tmux` 会话中注入 `TMUX` 环境变量用于嵌套识别；在重入时显式清理该变量可降低错误附着风险。[tmux man](https://man7.org/linux/man-pages/man1/tmux.1.html) | 一致。当前实现的清理策略可解释。 |
| 发送链路 | `send-and-verify`：`send-keys` + Enter + `capture-pane` 验证 | 官方 `send-keys` 与 `capture-pane` 提供基础命令，但不保证“输入即已落地”的语义；`-p` 导出 pane 内容可做回读校验。[tmux man（send-keys）](https://man7.org/linux/man-pages/man1/tmux.1.html), [tmux man（capture-pane）](https://man7.org/linux/man-pages/man1/tmux.1.html) | 一致并增强。当前比“盲发”稳得多。 |
| 命令定位 | `command -v tmux` + fallback 路径 | 路径发现应以运行时 PATH 优先，再做固定备选路径补偿。 | 一致。 |
| iTerm 权限 | 文档引导进入 `Automation` 白名单 | Apple 官方建议在 Privacy & Security/Automation 显式授予控制权限（按系统提示允许）[Apple 支持](https://support.apple.com/en-afri/guide/mac-help/mchl108e1718/mac) | 一致；建议把错误码输出挂到修复提示。 |
| iTerm 名称兼容 | `ITERM_SCRIPT_APPS=("iTerm","iTerm2")` 逐一重试 | macOS 与 iTerm 文档都建议遵循应用名变体并按实际可用值执行（避免硬编码单一 App 名） | 一致。 |
| 失败处理 | 失败即停、输出具体 `session/state/rc/错误码` | iTerm-only 约束下不做 GUI 降级 | 与目标约束一致。 |

## 2.2 与官方文档一致点
- iTerm 文档承认 AppleScript 与应用名兼容差异，不同版本命名可通过兼容处理对齐。
- tmux 文档将窗口/窗格内容、会话/命令作为文本输出机制，天然支持“发送后验证”二次确认。
- 运行时路径发现遵守“先动态再 fallback”是常见运维实践。

## 2.3 额外改进建议（非阻断）
- 在 `send-and-verify` 增加标准失败枚举码（如 `NOT_DELIVERED`、`TMUX_AUTH_BLOCKED`）可便于告警系统统一处理。
- 在 `check-engineer-status` 与 `send-and-verify` 之间复用同一 `tmux` 二进制解析函数，减少重复与漂移。

## 3. 运行时诊断路径（按优先级）
1. `tmux`：`tmux list-sessions` + `tmux_has_session`（会话存在性）  
2. 命令下发：`send-and-verify` 输出日志（`CAPTURE_BEFORE`/`AFTER`、`RETRY_*`）  
3. 窗口构建：`agent_admin_window.py` monitor 重建异常会回滚并保留故障上下文  
4. 现场修复：`tmux` 进程与 iTerm Script 授权核验

## 3.1 稳定恢复原则
- 对于 `tabs-1up` 项目，`agent-admin window open-monitor <project>` 是唯一推荐的窗口修复动作
- 它会按 canonical seat 顺序重建同一个项目窗口，不需要手工逐个 `tmux attach`
- 如果之前误开了多个同项目窗口，修复命令会清理旧窗口并恢复到单窗口多 tab 的布局
- koder 的日常维护只需要记住这一个入口；不要把窗口维护分散到多个手工命令里

## 3.1.1 Workers 窗口 pane 错连恢复（install 布局专用）

现象：worker pane（planner/builder/designer）里显示的是 **memory 的 TUI 内容**，而不是自己 seat 的 Claude/Codex/Gemini 界面。

根因（已观察）：workers 窗口开窗时（install.sh Step 7a）worker tmux session 可能还没存在；每个 pane 的 `wait-for-seat.sh` 在那个瞬态里可能错 attach 到 `<project>-memory`（目前已被 round-3+ 严格化，但旧窗口仍可能卡在此状态）。tmux-attach 阻塞成功后 while-true 循环不再 iterate，即便 canonical seat 后来起来也不会自动切回。

诊断：
```bash
env -u TMUX tmux list-clients -t '=<project>-memory'
# 正常：1 个 client（memory tab 自己）
# 错连：多个 client（memory + 错位 worker pane）
```

修复：
```bash
bash ${CLAWSEAT_ROOT}/scripts/recover-grid.sh <project>
# 等价手动操作：detach 所有 <project>-memory 的多余 client
# 每个被 detach 的 pane 的 wait-for-seat.sh 会自动 re-resolve + attach 到 canonical seat
```

幂等：`recover-grid.sh` 若发现 memory 只有 1 个 client，直接 `ok` 退出，不做任何动作。

与 `window open-grid` 的区别：
- `recover-grid.sh` — **保留现有 workers 窗口 + pane**，只修正 client 路由；首选。
- `window open-grid` — **新开 iTerm 窗口**；整个窗口丢失时使用。

## 4. 错误语义建议回看（快速）
- `TMUX_MISSING`：`command -v tmux` 及 fallback 均失败，优先修环境变量与安装。  
- `SESSION_NOT_FOUND`：会话映射失败，优先 `agent_admin` 重建会话绑定。  
- `RETRY_NEEDED`/`RETRY_FAILED`：发送命令仍停留在输入态，优先人工确认输入焦点状态。  
- `TMUX_CAPTURE_FAILED`：pane 不可读，优先确认会话是否存活、pane 是否在前端阻塞。  

## 5. 与安装 / 重入入口的衔接
- v0.7 主链路默认走 `docs/INSTALL.md` 与 `scripts/install.sh`：预检、环境扫描、memory 拉起、workers 窗口与 memories 窗口由 install.sh 完成，然后交给 memory 接手后续席位。
- 旧 direct primary-seat relaunch helper 已删除；fresh install 的 canonical 入口只有 `scripts/install.sh`。
- 若链路失败，当前实现会给出可执行修复建议，不做非阻断 GUI 降级。
