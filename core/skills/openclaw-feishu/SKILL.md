---
name: openclaw-feishu
description: >
  OpenClaw Feishu/Lark channel and ClawSeat koder troubleshooting playbook. Use
  when configuring a dedicated Feishu bot/account, binding an OpenClaw agent to a
  Feishu group, diagnosing inbound delivery, visible replies, message_tool vs
  automatic replies, group allowlists, mention policy, or ClawSeat koder bridge
  behavior. Must verify against official OpenClaw docs, user-provided docs when
  accessible, and upstream ClawSeat/OpenClaw source before changing behavior. Do
  NOT use to invent custom Feishu SDK paths, expose secrets, or bypass privacy
  boundaries.
version: 1.1.0
status: stable
---

# OpenClaw Feishu / Lark for ClawSeat

This skill is the standard playbook for OpenClaw Feishu/Lark channel setup and
ClawSeat koder troubleshooting.

Core rule: **do not 闭门造车**. Check official docs, user-provided docs, and
upstream source before proposing fixes.

## 0. Non-Negotiables

- Do not print, summarize, commit, or store real App Secrets, access tokens,
  refresh tokens, cookies, session values, or webhook secrets.
- Do not modify the default/original OpenClaw account when the task is about a
  dedicated ClawSeat account unless the user explicitly authorizes it.
- Do not send external Feishu messages unless the user asks for a live test.
- Do not implement a new Feishu SDK path in ClawSeat. OpenClaw owns channels;
  ClawSeat owns seat workflow and tmux transport.
- Prefer scoped account/group config over global config changes.

## 1. Research Gate First

Before changing behavior, verify in this order:

1. User-provided docs, if accessible. If a LarkOffice/Feishu document is private
   or unauthenticated, state that limitation and ask for an exported copy or
   pasted excerpt.
2. Official OpenClaw docs:
   - `https://docs.openclaw.ai/channels/feishu`
   - `https://docs.openclaw.ai/channels/groups`
   - `https://docs.openclaw.ai/gateway/config-channels`
   - `https://docs.openclaw.ai/message`
3. Local installed OpenClaw docs/source when web fetch is blocked:
   - `openclaw/docs/channels/feishu.md`
   - `openclaw/docs/channels/groups.md`
   - `openclaw/docs/gateway/config-channels.md`
   - OpenClaw `dist` source for the exact installed version
4. Upstream ClawSeat repo and local ClawSeat docs:
   - `https://github.com/KaneOrca/ClawSeat`
   - `docs/OPENCLAW.md`
   - `docs/CANONICAL-FLOW.md`
   - `core/skills/clawseat-koder/SKILL.md`

If the docs/source disagree, trust the installed source for the current machine,
then note the upstream difference.

## 2. Mental Model

OpenClaw owns Feishu/Lark channel plumbing:

- app credentials and WebSocket/webhook event subscription
- multi-account routing
- group allowlist and mention policy
- `message` tool and visible reply delivery
- gateway logs and hot reload

ClawSeat owns project workflow:

- seat dispatch and completion
- tmux/send-and-verify transport
- durable handoff receipts
- optional koder bridge between Feishu users and project memory

Feishu is an optional remote control / broadcast surface. It must not replace the
canonical ClawSeat seat-to-seat path: `send-and-verify.sh` + handoff receipts.

## 3. Dedicated Account Checklist

For a dedicated ClawSeat Feishu bot/account, keep it isolated:

```json5
{
  channels: {
    feishu: {
      accounts: {
        clawseat: {
          enabled: true,
          name: "clawseat",
          appId: "cli_xxx",
          appSecret: "<secret-ref-or-local-secret>",
          connectionMode: "websocket",
          domain: "feishu",
          groups: {
            oc_xxx: { requireMention: false }
          }
        }
      }
    }
  },
  bindings: [
    {
      type: "route",
      agentId: "clawseat",
      match: { channel: "feishu", accountId: "clawseat" }
    }
  ]
}
```

Rules:

- Account-level `appId`/`appSecret` must be under
  `channels.feishu.accounts.<accountId>` for named accounts.
- Bind routes by `accountId` so the dedicated bot reaches the dedicated agent.
- Preserve top-level/default account settings unless the user asked to migrate
  them.
- For group access in allowlist mode, either add the group to `groupAllowFrom` or
  add an explicit `groups.<chat_id>` entry.

## 4. Required Feishu Side Checks

If OpenClaw can send outbound but does not receive group messages, verify Feishu
Developer Console first:

- Bot is added to the group.
- App is published/approved.
- Event subscription includes `im.message.receive_v1`.
- Persistent connection / WebSocket is selected when using `connectionMode:
  "websocket"`.
- Required permissions are granted, commonly including message and chat scopes
  plus contact/user-read scopes when sender names need resolving.

Outbound send success does not prove inbound events are configured.

## 5. Group Reply Diagnosis Ladder

When a Feishu group message does not get a visible reply:

1. Check gateway status and logs.
2. Confirm an inbound line exists for the target account, for example
   `feishu[clawseat]: received message ... (group)`.
3. Confirm it dispatches to the intended agent/session.
4. Confirm session transcript contains assistant output.
5. Check dispatch result:
   - `queuedFinal=true` or `replies>0` means visible delivery was queued/sent.
   - `queuedFinal=false, replies=0` with assistant text usually means visible
     reply policy suppressed final text.
6. Check `messages.groupChat.visibleReplies`.

Official OpenClaw behavior:

- Group/channel rooms default to
  `messages.groupChat.visibleReplies: "message_tool"`.
- In tool-only mode, normal final assistant text is private; visible output must
  use `message(action=send)`.
- If the model/runtime does not reliably call tools, OpenClaw docs recommend a
  stronger tool-calling model or `messages.groupChat.visibleReplies:
  "automatic"`.
- If `message` is unavailable under the active tool policy, OpenClaw falls back
  to automatic visible replies.

## 6. Preferred Fix Order

Use the narrowest safe fix.

### A. Best if model reliably calls tools

Keep group visible replies in `message_tool` mode and teach the agent to use
`message(action=send)`. Validate with a real source turn, not just a normal local
agent prompt.

### B. Scoped fallback for one dedicated group

If the model does not reliably call `message`, disable only the `message` tool
for that account/group to trigger OpenClaw's documented automatic fallback:

```json5
{
  channels: {
    feishu: {
      accounts: {
        clawseat: {
          groups: {
            oc_xxx: {
              requireMention: false,
              tools: { deny: ["message"] }
            }
          }
        }
      }
    }
  }
}
```

Expected local policy result:

```json
{
  "messageToolAvailable": false,
  "sourceReplyDeliveryMode": "automatic",
  "suppressDelivery": false
}
```

This is preferred over global `automatic` when the user wants to avoid affecting
other OpenClaw accounts/groups.

### C. Global fallback

Only if the user accepts the blast radius:

```json5
{
  messages: {
    groupChat: { visibleReplies: "automatic" }
  }
}
```

This can affect every group/channel source turn in the OpenClaw config.

## 7. Validation Without Sending Feishu Messages

Use local read-only checks before live tests:

- `openclaw gateway status --json` — gateway running and config audit OK.
- Config inspection with redacted secrets.
- Installed OpenClaw source/docs to verify policy behavior for the current
  version.
- Gateway logs for hot reload lines such as:
  - `config change detected; evaluating reload (...)`
  - `config hot reload applied (...)`
  - `feishu[account]: WebSocket client started`

For policy validation, simulate only the config-derived behavior:

- group tool policy resolves to `deny: ["message"]`
- `messageToolAvailable` is false
- source reply delivery mode resolves to `automatic`
- `suppressDelivery` is false

Do not send a live Feishu test unless the user asks.

## 8. Live Test Acceptance

When the user asks for a live test or reports they sent a message:

1. Watch logs for inbound event under the right account.
2. Verify dispatch to the intended agent/session.
3. Verify dispatch completes with visible output:
   - `queuedFinal=true`, or
   - `replies=1` or greater.
4. Ask the user whether the group saw the reply if logs are ambiguous.

Do not repeatedly send test messages yourself. One explicit test is enough.

## 9. ClawSeat Alignment

ClawSeat's upstream docs describe OpenClaw as the channel/control-plane layer and
ClawSeat as the local seat workflow layer.

Keep these boundaries:

- Feishu/koder is optional remote frontstage and notification surface.
- Project memory remains the ClawSeat frontstage for local workflow.
- Seat-to-seat work uses tmux and `send-and-verify.sh`.
- Handoff completion requires durable artifacts and receipts.
- Koder should route project/business work to memory rather than dispatching
  specialists directly.

## 10. Windows/WSL Direct Closeout Playbook

Use this when ClawSeat Windows completed the local chain but the Feishu group did
not receive the final planner report.

Validated shape:

- Windows/PowerShell is only the entry/control plane.
- WSL Ubuntu is the runtime for `lark-cli`, tmux seats, and ClawSeat scripts.
- WezTerm is display-only.
- OpenClaw may listen to group messages and dispatch into planner, but final
  planner closeout can be sent directly through `lark-cli`; it must not depend on
  OpenClaw home/config.
- The canonical chain remains planner -> builder/reviewer/patrol -> planner ->
  memory, with durable receipts.

### Preconditions

In WSL, verify:

```bash
lark-cli auth status --verify
python3.11 /mnt/e/trae\ solo/ClawSeat-Windows/core/skills/gstack-harness/scripts/send_delegation_report.py \
  --project pbr \
  --lane planning \
  --task-id pbr-closeout-smoke \
  --report-status done \
  --decision-hint proceed \
  --user-gate none \
  --next-action finalize_chain \
  --summary "dry-run final closeout smoke" \
  --dry-run
```

Expected:

- `lark-cli` is configured and token status is valid or refreshable.
- Dry-run prints `delegation-report: project=pbr -> group=...`.
- The group comes from `~/.agents/tasks/pbr/PROJECT_BINDING.toml`.
- No command requires `~/.openclaw` as cwd.

### Bot Send Path

Use when only app/bot identity is needed. The command below sends a real Feishu
message; run it only after explicit user approval.

```bash
lark-cli config init --new
python3.11 /mnt/e/trae\ solo/ClawSeat-Windows/core/skills/gstack-harness/scripts/send_delegation_report.py \
  --project pbr \
  --lane planning \
  --task-id pbr-bot-smoke \
  --report-status done \
  --decision-hint proceed \
  --user-gate none \
  --next-action finalize_chain \
  --summary "pbr bot smoke complete" \
  --as bot
```

Success means JSON includes:

```json
{
  "status": "sent",
  "transport": "lark-cli-bot",
  "group_id": "oc_..."
}
```

If Feishu returns `Bot/User can NOT be out of the chat`, add the bot to the target
Feishu group, then retry once.

### User Identity Path

Use when OpenClaw should interpret the message as the human user.

```bash
lark-cli auth login --recommend
lark-cli auth login --scope "im:message.send_as_user"
lark-cli auth status --verify
```

Expected status includes:

- `identity: user`
- the expected human user name
- `tokenStatus: valid`

Then send a group trigger using the user identity. This sends a real Feishu
message and can trigger OpenClaw; run it only after explicit user approval.

```bash
lark-cli --as user im +messages-send \
  --chat-id oc_... \
  --text "@clawseat pbr-mini-004: 请 planner 创建 status_check.txt，内容 ok，然后让 memory 归档并在群里汇报。"
```

Success criteria:

- OpenClaw logs show the group message was received and routed to the ClawSeat
  agent.
- Planner dispatches work into the pbr seat chain.
- Memory consumes the final closeout.
- The planner->memory receipt records direct Feishu delivery.

### Seat State Checks

Use tmux and durable files, not Feishu history search, as the source of truth.

```bash
tmux ls | grep -E "pbr-(planner|builder|reviewer|memory|patrol)-claude"
cat ~/.agents/tasks/pbr/STATUS.md
ls -t ~/.agents/tasks/pbr/patrol/handoffs | head
```

Inspect the latest planner->memory receipt:

```bash
python3.11 - <<'PY'
import json
from pathlib import Path
root = Path.home() / ".agents/tasks/pbr/patrol/handoffs"
path = next(p for p in sorted(root.glob("*__planner__memory.json"), key=lambda p: p.stat().st_mtime, reverse=True))
data = json.loads(path.read_text())
print(path)
print(data.get("task_id"))
print(data.get("status"))
print(data.get("feishu_delegation_report", {}).get("status"))
print(data.get("feishu_delegation_report", {}).get("transport"))
print(data.get("feishu_delegation_report", {}).get("message_id"))
PY
```

Expected final closeout receipt:

```text
status = completed
feishu_delegation_report.status = sent
feishu_delegation_report.transport = lark-cli-user or lark-cli-bot
feishu_delegation_report.message_id = om_...
```

### Direct Closeout Contract

Planner final group reports should use the current direct-closeout implementation's
`OC_DELEGATION_REPORT_V1` shape with:

```text
lane: planning
report_status: done
decision_hint: proceed
user_gate: none
next_action: finalize_chain
```

If a downstream koder consumer requires the older canonical `done + close + none +
finalize_chain` mapping, update `complete_handoff.py` and its contract tests
before changing this skill.

The human-readable tail may include bullets and blank lines. Preserve newlines so
the group sees an readable final report, for example:

```text
pbr-mini-004 COMPLETE.
- status_check.txt 创建，内容 ok
- planner -> memory receipt 写入

当前链路状态：
- memory 已消费 closeout
- chain 已 close
```

## 11. Failure Mode Ladder

Use exact error text to choose the next action.

| Symptom | Meaning | Fix |
| --- | --- | --- |
| `not configured` | `lark-cli` has no app config | Run `lark-cli config init --new` in WSL |
| `No user logged in` or `need_user_authorization` | Bot exists, user OAuth missing | Run `lark-cli auth login --recommend` |
| `missing required scope(s): im:message.send_as_user` | User OAuth lacks send scope | Run `lark-cli auth login --scope "im:message.send_as_user"` |
| `Bot/User can NOT be out of the chat` | Current identity is not in target group | Invite/bind the bot or user to the group |
| `FileNotFoundError ... ~/.openclaw` | Feishu send path is wrongly coupled to OpenClaw home | Use `_lark_cli_cwd()` and strip inherited `OPENCLAW_HOME` |
| `missing required scope(s): search:message` | Only message search is unauthorized | Do not add this scope unless search is actually needed |
| Receipt has no `feishu_delegation_report` | Closeout did not run direct Feishu sender | Check planner->memory final closeout path |
| `STATUS.md` says a seat is dead but tmux shows attached | Status file may be stale | Trust tmux plus latest receipts, then refresh status separately |

## 12. Anti-Patterns

- Guessing Feishu/OpenClaw config without checking official docs or installed
  source.
- Treating outbound send success as proof that inbound event subscription works.
- Changing global `messages.groupChat.visibleReplies` when a per-account/per-group
  policy solves the problem.
- Editing OpenClaw installed source instead of using supported config, unless the
  user explicitly asks for a temporary local patch.
- Exposing App Secret or tokens in summaries, memory, docs, logs, or commits.
- Making Feishu the canonical ClawSeat seat transport.
- Requiring OpenClaw home/config for planner final Feishu closeout.
- Flattening multi-line closeout summaries into unreadable one-line reports.

## 13. Useful References

- Official OpenClaw Feishu docs: `https://docs.openclaw.ai/channels/feishu`
- Official OpenClaw group docs: `https://docs.openclaw.ai/channels/groups`
- Official channel config docs: `https://docs.openclaw.ai/gateway/config-channels`
- Official message CLI docs: `https://docs.openclaw.ai/message`
- Upstream ClawSeat: `https://github.com/KaneOrca/ClawSeat`
- Local ClawSeat docs: `docs/OPENCLAW.md`, `docs/CANONICAL-FLOW.md`
