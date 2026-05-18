---
name: clawseat-privacy
description: >
  Privacy gate for ClawSeat messages, commits, and artifacts that may expose
  secrets or sensitive operator data. Use when preparing broadcasts, Feishu
  messages, DELIVERY summaries, commits, logs, or any content containing
  tokens, API keys, credentials, private paths, or customer data. Also use when
  a seat suspects accidental leakage. Covers secret detection, redaction
  guidance, and escalation for unsafe content. Do NOT use for general code
  review, product decisions, or approving content that has not been inspected.
version: "1.0"
status: draft
author: machine-memory
review_owner: operator
spec_documents:
  - docs/rfc/RFC-002-architecture-v2.1.md (§9)
related_skills:
  - clawseat-koder (broadcast 前必查)
  - clawseat-decision-escalation (升级 secret 类必带相关检查)
---

# clawseat-privacy (v1)

> **what**: 强制所有 seat 在执行任何"对外暴露"动作前读 privacy KB，命中黑名单则 hard fail。
> **why**: ClawSeat 系统接触 OAuth token / API key / customer name / endpoint URL 等敏感信息，多 seat 多 project 拓扑下任一 seat 的疏忽都可能导致泄漏（commit 进 git / 广播到 Feishu / publish 到 OSS）。需要单点 SSOT 隐私清单 + 强制检查。
> **how**: machine-level 1 文件 + 所有 seat skill reference 本 skill + pre-action read + 命中即 fail。

---

## 1. 路径 + 范围

- **SSOT**: `~/.agents/memory/machine/privacy.md`
- **作用域**: machine-level（跨所有 project，跨所有 seat）
- **维护人**: operator（手动 append）+ machine-memory（自动 append 发现的新 pattern）
- **读者**: 所有 seat（memory / planner / builder / designer / koder）

---

## 2. privacy.md 文件格式

```markdown
# Privacy KB (machine-level)

> 所有 seat 在 commit / Feishu broadcast / 外部 publish 前必须读本文件。命中任何模式 → hard fail。
> 维护: operator 手动 append；machine-memory 在新 pattern 被自动发现时 append。

## 不可暴露 — 字面 token / key

- MINIMAX_CREDENTIAL_PATTERN  (MiniMax token 模式)
- ANTHROPIC_CREDENTIAL_PATTERN (Anthropic key 模式)
- OPENAI_PROJECT_CREDENTIAL_PATTERN (OpenAI project key)
- AKIA*    (AWS access key)
- ghp_*    (GitHub personal access token)
- ghs_*    (GitHub server token)

## 不可暴露 — 字面 endpoint

- api.minimaxi.com
- ark.cn-beijing.volces.com
- xcode.best/v1
- (operator append 内部 endpoint 这里)

## 不可暴露 — 项目 / 客户名

- (operator 在这里手动 append 客户公司名 / 内部 project codename)

## 不可暴露 — 路径模式

- ~/.agents/secrets/**
- ~/.openclaw/credentials/**
- ~/.config/gh/hosts.yml

## 不可暴露 — 飞书 group / app id

- oc_*  (Feishu chat_id)
- cli_*  (Feishu app_id starting with cli, 内部 OpenClaw bot)

## Sanitize 规则

- token 模式 → 替换 `sk-***MASKED***`
- endpoint → 替换 `https://internal-api.example.com`
- 客户名 → 替换 `<CUSTOMER>`
- 路径 → 替换 `<HOME>/.agents/secrets/<MASKED>`
```

---

## 3. Pre-action 强制检查

任何 seat 在以下动作前**必须** read privacy.md + scan target content:

| 动作 | scan target |
|------|-------------|
| `git commit` | staged diff 全文 |
| `git push` | 所有 unpushed commits 的 diff |
| Feishu broadcast | message 文本 + 任何 supporting docs |
| `publish` 类操作（OSS / npm / pypi）| 即将发布的 artifacts 全部内容 |
| 任何 `osascript` `display notification` 含动态文本 | notification 文本 |
| 任何 `curl` POST 到外部 endpoint | request body |
| 任何 `tmux send-keys` 跨项目 | 发送内容 |

**实施**: 每个 seat 的 skill 必须在以上动作前 invoke 本 skill 的检查 helper:

```bash
bash core/scripts/privacy-check.sh <action_type> <content_or_path>
# exit 0 = pass; exit 1 = blocked + stderr 含 matched pattern
```

---

## 4. 命中处理

命中黑名单 → **hard fail**:

1. 立即停止当前动作（不 commit / 不 broadcast / 不 push）
2. 输出明确错误:
   ```
   PRIVACY_BLOCK
   matched_pattern: fixture-minimax-value (MiniMax token)
   matched_in: <file path or context>
   sanitize_suggestion: 替换为 sk-***MASKED*** 后重试
   ```
3. 如果是 koder broadcast → tmux-send memory: `PRIVACY_BLOCK decision_id=<uuid> matched=<pattern>`
4. 如果是 commit → git restore staged，提示 operator 手动 sanitize
5. 不允许 `--force` / `--no-verify` 绕过

---

## 5. operator 维护

operator 通过以下方式更新:

- 手动 edit `~/.agents/memory/machine/privacy.md`
- machine-memory 发现新 pattern → 追加 + tmux-send operator："已自动追加新隐私模式 X，请确认"
- operator 可通过 git history 查 privacy.md 演进

memory **不许**自动删除黑名单项（只能追加 + 注释 deprecated）。

---

## 6. 自动发现新 pattern

machine-memory 在以下场景**主动**追加新 pattern:

- 看到 commit / broadcast 内容含未黑名单的 token 样式 string（如新的 `xyz-abc-123` 看起来像 secret）
- 飞书消息含新 endpoint URL 模式
- learning notes 提到新客户/项目代号

追加格式:
```markdown
## 不可暴露 — 字面 token / key (auto-appended 2026-04-26)

- xyz-abc-* (suspected by machine-memory @ commit abc123, operator 请确认)
```

operator 没确认前，pattern 仍生效（safer default）。

---

## 7. 反模式

| 反模式 | 后果 | 替代 |
|--------|------|------|
| 跳过 pre-action check | 隐私泄漏 | 永远 invoke privacy-check.sh |
| 用 `git commit --no-verify` 绕过 | 黑名单失效 | 修内容，不绕过 |
| operator override hard fail | 单次绕过变常态 | hard fail 设计上无 override |
| privacy.md 本身 commit 进公开仓库 | 黑名单泄漏（虽然只是 pattern 不是 value）| privacy.md 留在 ~/.agents（不进 worktree）|
| 把 token value 直接贴 chat 求助 | operator 也违反 | 永远先 sanitize |

---

## 8. 验收

- `core/scripts/privacy-check.sh` 实现 + 在 install.sh 安装时被注册
- 所有 5 个 seat skill (memory/planner/builder/designer/koder) 都 reference 本 skill
- commit hook (pre-commit) invoke privacy-check.sh
- 至少 1 次实测 hard fail（故意 commit 含 sk-* 字样应被拒）
- privacy.md starter 文件提交到 `~/.agents/memory/machine/privacy.md`（**不进 worktree git**）
