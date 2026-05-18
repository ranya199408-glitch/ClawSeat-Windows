# Feishu 3-Layer Architecture

ClawSeat Feishu routing only makes sense if you keep three layers separate:

1. the `lark-cli` user/tool app that sends `OC_DELEGATION_REPORT_V1`
2. the OpenClaw agent app configured for a specific account
3. the chat membership list that tells you whether the user can actually reach a group

Do not collapse those layers into a single "Feishu is configured" boolean. Most
send failures, especially `230027`, come from mixing up app identity, chat
membership, and project binding.

## The Three Layers

| Layer | Canonical source | What it answers | What it does NOT answer |
|---|---|---|---|
| L1: `lark-cli` tool app | `~/.lark-cli/config.json` | Which user-scoped tool app `lark-cli --as user` is using | Which OpenClaw agent app is active |
| L2: OpenClaw agent app | `~/.openclaw/openclaw.json` → `channels.feishu.accounts.<account>.appId` | Which Feishu app an OpenClaw account uses as a bot/agent identity | Whether the user is in a given chat |
| L3: chat membership SSOT | `lark-cli im chats list --as user --page-all` | Which chats the current user can actually see and whether they are external | Which project should bind to which chat |

### L1 — `lark-cli` tool app

- File: `~/.lark-cli/config.json`
- Typical use: `send_delegation_report.py` and other user-identity sends through
  `lark-cli --as user`
- Operational meaning: this is the auth/config for the tool app currently driving
  `lark-cli`
- Limitation: scope is controlled by the tool app; if that app cannot send to an
  external chat, no amount of OpenClaw account tweaking fixes it

### L2 — OpenClaw agent app

- File: `~/.openclaw/openclaw.json`
- Field: `channels.feishu.accounts.<account>.appId`
- Typical use: OpenClaw gateway sends as a specific agent account
- Operational meaning: each OpenClaw account can map to a different Feishu app
- Limitation: this layer is not the chat-membership source of truth; it only tells
  you which app an agent would use

### L3 — chat membership SSOT

- Command: `lark-cli im chats list --as user --page-all`
- Key fields: `chat_id`, `name`, `external`, `tenant_key`, `owner_id`,
  `chat_status`
- Operational meaning: this is the real user-visible chat inventory
- Rule: if a chat does not appear here, treat "user can send there" as false until
  proven otherwise

## Project Binding vs Chat Discovery

Different questions have different sources of truth:

- "Which chat should project `X` use?" → project binding plus strict resolver
- "Can the current user identity actually see/send to chat `oc_...`?" → L3 chat list
- "Which Feishu app is OpenClaw account `koder` using?" → L2 `openclaw.json`

For project-scoped group resolution, use
`core/skills/gstack-harness/scripts/_feishu.py:resolve_feishu_group_strict()`.
Its contract is intentionally narrow:

1. `CLAWSEAT_FEISHU_GROUP_ID` or `OPENCLAW_FEISHU_GROUP_ID`
2. `~/.agents/tasks/<project>/PROJECT_BINDING.toml`
3. the project's `WORKSPACE_CONTRACT.toml`

It does **not** guess from global `openclaw.json` or `sessions.json`. That guardrail
exists to prevent cross-project misroutes.

Related files:

- `core/lib/project_binding.py` — `PROJECT_BINDING.toml` schema and helpers
- `~/.agents/tasks/<project>/PROJECT_BINDING.toml` — per-project binding SSOT
- `~/.agents/projects/<project>/BRIDGE.toml` — OpenClaw bridge binding state

## Memory Snapshot: `feishu.json`

The Feishu knowledge snapshot lives at `~/.agents/memory/machine/feishu.json`.
Treat it as the low-token read path for the three layers once the scanner has
captured them.

Expected top-level fields:

- `lark_cli` — L1 tool-app details
- `openclaw_accounts` — L2 agent-app list
- `user_chats` — L3 chat list
- `project_bindings` — enriched project binding records
- `validations` — cross-check results such as `user_in_chat`,
  `chat_is_internal`, and `user_identity_sendable`
- `diagnostics.error_230027_decision_tree` — the canonical send-failure checklist

If the snapshot is missing or stale, fall back to the live sources above.

## Canonical `chat_id` Lookup

Preferred order:

1. If `~/.agents/memory/machine/feishu.json` exists and is recent enough for the
   task, read it first.
2. Otherwise run the live L3 query:

```bash
lark-cli im chats list --as user --page-all
```

3. Match by exact `chat_id` when already known, or by chat name plus project context
   when the operator only knows the display name.

After `R6-K3` lands, the canonical higher-level query should be:

```bash
python3.11 "$CLAWSEAT_ROOT/core/skills/memory-oracle/scripts/query_memory.py" \
  --feishu --resolve "<project-or-chat-name>"
```

Until that lands, do not document `--feishu --resolve` as already available in the
current tree. Use direct `feishu.json` reads or the live `lark-cli` listing.

## `230027` Diagnosis Tree

When a Feishu send fails with `230027`, debug in this order:

1. `chat_id` correctness
   Re-resolve the target chat from L3. Do not assume a copied display name maps to
   the right `oc_...` id.
2. External-chat status
   Check whether the chat is `external=true`. External chats often require app
   capabilities the default `lark-cli` tool app does not have.
3. App membership
   Confirm the relevant app/bot was actually added to the target chat. User
   membership alone is insufficient.
4. User membership
   Confirm the current user identity appears to be in the chat via
   `lark-cli im chats list --as user --page-all`.
5. Identity sendability
   If the app, user, and chat all look correct, treat this as an auth/scope issue:
   re-check `lark-cli auth status`, redo `lark-cli auth login` if needed, and
   compare the sending identity against the expected L1 or L2 app.

This is the fast mental model:

- L1 failure: auth/scope/tool-app issue
- L2 failure: wrong OpenClaw account app or missing app config
- L3 failure: wrong chat, external chat, or membership mismatch

## Closeout Protocol

When a Feishu group is bound, emit structured closeouts with
`send_delegation_report.py`. Do not hand-write free-form status packets.

```bash
python3.11 <HARNESS_SCRIPTS>/send_delegation_report.py \
  --profile <PROFILE> \
  --task-id <TASK_ID> \
  --report-status done \
  --decision-hint proceed \
  --user-gate none \
  --next-action consume_closeout \
  --human-summary '<SHORT_PLAIN_LANGUAGE_SUMMARY>'
```

For interactive decision gates:

```bash
python3.11 <HARNESS_SCRIPTS>/send_delegation_report.py \
  --profile <PROFILE> \
  --task-id <TASK_ID> \
  --report-status needs_decision \
  --report-kind OC_DELEGATION_REPORT_V1 \
  --decision-hint ask_user \
  --user-gate required \
  --human-summary '<THE_SKILL_QUESTION_IN_PLAIN_CHINESE>'
```

Before the first send in a session:

```bash
python3.11 <HARNESS_SCRIPTS>/send_delegation_report.py --check-auth
```

If auth is not `ok`, tell the user: `请在有浏览器的终端运行 lark-cli auth login`.

The legacy group broadcast path remains disabled by default unless
`CLAWSEAT_ENABLE_LEGACY_FEISHU_BROADCAST=1` is explicitly set.

When a closeout arrives via Feishu user identity, trust the structured
`OC_DELEGATION_REPORT_V1` payload and the linked delivery trail, not the apparent
sender name alone.
