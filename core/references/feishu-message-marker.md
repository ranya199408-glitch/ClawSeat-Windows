# Feishu Message Marker

ClawSeat seats that push user-visible Feishu messages add a human-readable
prefix and a machine-readable footer. Koder can use both signals to route a
reply back to the correct TUI session.

## Format

```markdown
[Memory]
Message body.

---
_via Memory @ 2026-04-27T19:00:00Z | project=install | session=install-memory_
```

QA includes the mode in the prefix:

```markdown
[QA scope=patrol]
Message body.

---
_via QA @ 2026-04-27T19:00:00Z | project=install | session=install-qa_
```

## Message Types

All user-visible seats still use the unchanged `[Memory]` marker and footer for
routing; only the first line content changes by message type.

### 成功✅

```text
[Memory] ✅ 成功
<1~4 lines body>
---
_via Memory @ <ts> | project=<project> | session=<session>_
```

### BLOCKED🔴

```text
[Memory] 🔴 BLOCKED
<1~4 lines body>
---
_via Memory @ <ts> | project=<project> | session=<session>_
```

### 派工完成📋

```text
[Memory] 📋 派工完成
<1~4 lines body>
---
_via Memory @ <ts> | project=<project> | session=<session>_
```

Constraints:

- First line must remain a single-line marker starting with `[Memory]` and must
  include one of the three emoji/status forms above.
- Message body between first line and footer must be no more than 4 non-empty
  lines.
- Footer is fixed signature format for automatic routing:
  `_via <Seat> @ <UTC ISO8601> | project=<project> | session=<session>_`.

## Fields

- Prefix: `[Memory]`, `[QA scope=patrol]`, or `[QA scope=test]`.
- Seat: source seat name in the footer.
- Timestamp: UTC ISO8601, generated at send time.
- Project: from `CLAWSEAT_PROJECT`, `AGENTS_PROJECT`, payload metadata, or
  `unknown`.
- Session: from `tmux display-message -p '#S'`, or `unknown`.

## Parsing Rules

Recommended regex:

```text
^\[(?P<seat>Memory|QA)(?: scope=(?P<scope>patrol|test))?\]
^_via (?P=seat) @ (?P<ts>[^|]+) \| project=(?P<project>[^|]+) \| session=(?P<session>[^_]+)_$
```

Koder should require prefix and footer to agree on seat. For QA, the prefix
scope is authoritative. If the footer is missing or malformed, Koder may still
display the message but should not use it for automatic routing.

## Anti-Spoofing

This is not cryptographic authentication. It is a dual-signal convention:
humans see the source at the top, and automation verifies the footer plus tmux
session. Forged user text without the correct footer should be treated as
unroutable.

## Sender

- Stop hooks add the prefix and footer automatically.
- Seats should not manually include the marker in normal prose.
- Missing tmux session must fall back to `session=unknown`.
- `LARK_CLI_NO_PROXY=1` must be set when invoking Lark CLI sender paths.
- Default CLI argument is `--as user`.
