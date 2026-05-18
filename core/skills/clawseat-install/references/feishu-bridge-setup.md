# Feishu Bridge Setup & Smoke Test

> **Canonical SOP**: This file is the reference guide for the 7-step Feishu bridge setup.
> Fresh installs should follow [`docs/INSTALL.md`](../../../../docs/INSTALL.md),
> then let ancestor execute the bridge-related steps from the runtime brief.

## Prerequisites

- `lark-cli` installed and in PATH (`brew install larksuite/cli/lark-cli` or check `which lark-cli`)
- OpenClaw gateway running
- A Feishu group that the project bot has been added to

## Event Scope Checklist

Before testing Feishu dispatch, confirm these are enabled in Feishu Open Platform → App → Event Subscriptions:

| Scope | Purpose | Required |
|---|---|---|
| `im:message` | 聊天消息事件 | Yes |
| `im:message.group_msg:receive` | 群消息免@ — koder responds without @mention | **Critical** |
| `im:chat:access` | 聊天管理 | Yes |

And in Permissions & Scopes:

| Permission | Purpose | Required |
|---|---|---|
| `im:chat` | 读写群消息 | Yes |
| `im:chat.members` | 读取群成员 | Yes |

After enabling scopes, publish a new app version (版本管理与发布 → 提交审核 → 发布). Scope changes are not active until published.

## Step 1: Verify lark-cli auth

Use the built-in auth check before anything else:

```bash
python3 $CLAWSEAT_ROOT/core/skills/gstack-harness/scripts/send_delegation_report.py --check-auth
```

Expected output when healthy:

```json
{
  "identity": "user",
  "reason": "auth token is valid",
  "status": "ok",
  "userName": "your_name"
}
```

If `status` is not `ok`, follow the `fix` field in the output. Most common fix:

```bash
lark-cli auth login
```

Follow the browser prompt to complete OAuth. This is a **user action** — the
agent cannot complete it automatically.

**Important for tmux seats**: lark-cli auth config lives under the **real user
HOME**, not the isolated seat runtime HOME. The ClawSeat scripts handle this
automatically by passing `AGENT_HOME` to the lark-cli environment. If you see
auth failures from a tmux seat but `lark-cli auth status` works in your normal
terminal, check that `AGENT_HOME` is correctly set in the seat's environment.

## Step 2: Collect Feishu group ID

Ask the user for the Feishu group ID. It can be found:

- In the Feishu admin panel under group settings
- By scanning OpenClaw sessions: `python3 $CLAWSEAT_ROOT/core/skills/clawseat-install/scripts/find_feishu_group_ids.py`
- From `sessions.json` keys with `group:` prefix

Format: `oc_` followed by a hex string (e.g. `<FEISHU_GROUP_ID>`)

## Step 3: Confirm project-group binding

Before binding, koder must confirm with the user:

1. Is this group for the **current project**?
2. Or should it **switch to an existing project**?
3. Or should it **create a new project** for this group?

One project = one group. One group = one project.

## Step 4: Bind the project to the group

Planner (or koder via adapter) calls:

```python
bind_project_to_group(
    project="install",
    group_id="oc_xxx",
    account_id="<koder_app_id>",
    session_key="<openclaw_session_key>",
    bound_by="<user>",
    authorized=True,
)
```

This writes `~/.agents/projects/install/BRIDGE.toml`.

## Step 5: Configure requireMention

- Main agent (koder-facing OpenClaw): `requireMention: true` (default)
- Project koder account in group: `requireMention: false`

See `references/feishu-group-no-mention.md` for configuration details.

## Step 6: Smoke test

First do a dry-run to verify the envelope is well-formed:

```bash
python3 $CLAWSEAT_ROOT/core/skills/gstack-harness/scripts/send_delegation_report.py \
  --project install \
  --lane planning \
  --task-id BRIDGE-SMOKE-001 \
  --report-status done \
  --decision-hint proceed \
  --user-gate none \
  --next-action consume_closeout \
  --summary 'Feishu bridge smoke test' \
  --dry-run
```

Then send for real (the script auto-checks auth before sending):

```bash
python3 $CLAWSEAT_ROOT/core/skills/gstack-harness/scripts/send_delegation_report.py \
  --project install \
  --lane planning \
  --task-id BRIDGE-SMOKE-001 \
  --report-status done \
  --decision-hint proceed \
  --user-gate none \
  --next-action consume_closeout \
  --summary 'Feishu bridge smoke test — if you see this message, the bridge is working' \
  --chat-id oc_xxx
```

Tell the user: `收到测试消息即可回复希望完成什么任务`

If the message arrives in the Feishu group, the bridge is working.

## Step 7: Verify koder can parse the report

Koder should receive the `OC_DELEGATION_REPORT_V1` envelope in the group and verify:

- `project=install` matches
- `task_id=BRIDGE-SMOKE-001` matches
- `report_status=done` + `next_action=consume_closeout` → auto-advance

## Troubleshooting

### lark-cli `---WAIT---` during auth

If you see `---WAIT---` in lark-cli output during `lark-cli auth login`, this is **normal device flow polling** — lark-cli is waiting for the user to approve in a browser. Do NOT kill the process. Wait for the browser approval, or press Ctrl-C and retry with a browser-accessible terminal.

### Quick diagnosis

```bash
# 1. Is lark-cli installed?
which lark-cli

# 2. Is auth valid?
python3 $CLAWSEAT_ROOT/core/skills/gstack-harness/scripts/send_delegation_report.py --check-auth

# 3. Can we resolve a group ID?
python3 $CLAWSEAT_ROOT/core/skills/clawseat-install/scripts/find_feishu_group_ids.py

# 4. Is the env var set? (for tmux seats)
echo $CLAWSEAT_FEISHU_GROUP_ID
```

### Error reference

| Error reason in send result | Meaning | Fix |
|-----------------------------|---------|-----|
| `lark_cli_missing` | lark-cli binary not in PATH | `brew install larksuite/cli/lark-cli` |
| `auth_expired` | OAuth token expired | User runs `lark-cli auth login` in a terminal with browser access |
| `auth_needs_refresh` | Token needs refresh | User runs `lark-cli auth login` |
| `permission_denied` | Missing `im:message` scope | Re-run `lark-cli auth login` and ensure the OAuth scope includes `im:message` |
| `group_not_found` | Group ID invalid or bot not in group | Verify group ID; ensure the bot app is added to the target group in Feishu admin |
| `event scope missing` | 群消息 not delivered without @mention | Enable `im:message.group_msg:receive` in Feishu Open Platform → Event Subscriptions, then publish a new app version |
| `network_error` | Network connectivity issue | Check internet; retry |
| `no_group_id_found` | No group ID resolved from env/config/sessions | Pass `--chat-id` explicitly or `export CLAWSEAT_FEISHU_GROUP_ID=oc_xxx` |

### Common scenarios

**Scenario: planner in tmux can't send but terminal works**

lark-cli auth lives in the real user HOME. The isolated seat HOME is different.
ClawSeat passes `AGENT_HOME` as the real HOME to lark-cli, but if `AGENT_HOME`
is not set (e.g. manual tmux session), lark-cli will look in the wrong place.

Fix: ensure `AGENT_HOME` is exported in the seat environment, or run
`start_seat.py` which handles this automatically.

**Scenario: token expires mid-session**

lark-cli tokens have a limited lifetime. If a long-running planner session
eventually fails to send, the token has likely expired.

Fix: user runs `lark-cli auth login` in any terminal. The refreshed token is
stored under the real HOME and will be picked up by the next send attempt
from any seat.

**Scenario: message sent but koder doesn't see it**

1. Check `requireMention` config — koder account must be `requireMention: false`
   for the target group
2. Restart OpenClaw gateway after config changes: `cd openclaw && pnpm openclaw gateway restart`
3. Verify the bot app has `im:message:receive` permission in Feishu developer console

**Scenario: koder sees the message but doesn't auto-advance**

1. Verify the envelope has all 9 required fields
2. Check `project` matches the active project in koder
3. Check `task_id` and `dispatch_nonce` match the active delegation chain
4. Use `--dry-run` to inspect the envelope before sending
