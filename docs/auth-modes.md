# Auth modes for Claude seats

ClawSeat supports four `auth_mode` values for `tool=claude`. Each maps to
a different credential source; choose based on the seat's risk profile and
operational constraints.

## Modes

### `oauth` (legacy)

The default Anthropic OAuth flow. Credentials are stored in the macOS
Keychain. **Problem:** each seat runs in an isolated sandbox HOME, so
every seat has its own Keychain slot. When the session expires, an
interactive popup blocks the seat until the operator clicks through — not
dismissable from automation.

**Avoid for new seats.** Existing `oauth` seats should be migrated to
`oauth_token` or `api/anthropic-console`.

### `oauth_token`

Long-lived (~1 year) token obtained via `claude setup-token` on the
operator host. Stored in a secret file as `CLAUDE_CODE_OAUTH_TOKEN`.
Bypasses the Keychain entirely — no popup on restart.

**Secret file** must contain:
```
CLAUDE_CODE_OAUTH_TOKEN=<CLAUDE_CODE_OAUTH_TOKEN>
```

Obtain via:
```
claude setup-token
# Copy the printed token, then:
echo 'export CLAUDE_CODE_OAUTH_TOKEN=<CLAUDE_CODE_OAUTH_TOKEN> >> ~/.agents/.env.global
```

### `api` + `anthropic-console` provider

Direct call to `api.anthropic.com` using an `ANTHROPIC_API_KEY` created
in the Anthropic Console UI under the "Claude Code" scoped-role. Distinct
from Developer API keys — this key is not subject to Keychain or OAuth
expiry.

**Secret file** (`~/.agents/secrets/claude/anthropic-console.env`) must contain:
```
ANTHROPIC_API_KEY=<ANTHROPIC_API_KEY>
```

Create via Anthropic Console → API Keys → New key (scoped role: Claude Code):
```
mkdir -p ~/.agents/secrets/claude
echo 'ANTHROPIC_API_KEY=<ANTHROPIC_API_KEY> > ~/.agents/secrets/claude/anthropic-console.env
chmod 600 ~/.agents/secrets/claude/anthropic-console.env
```

### `ccr` + `ccr-local` provider

Routes through a local Claude Code Router proxy (`ccr start`). The proxy
holds all upstream provider keys and multiplexes them per-request. The
seat injects `ANTHROPIC_BASE_URL=http://127.0.0.1:3456` and a dummy auth
token — no secret file required on the seat side.

Use for seats that need provider diversity or when upstream API keys are
managed centrally by CCR.

## Decision guide

| Situation | Recommended mode |
|-----------|-----------------|
| New claude seat, Anthropic direct | `oauth_token` |
| Seat needs isolation / diversity | `api/anthropic-console` |
| Multi-provider routing via CCR | `ccr/ccr-local` |
| Legacy seat (pre-A1) | Migrate with `migrate-seat-auth` |

## Migration guide (A1)

To migrate existing `oauth` seats, use `migrate-seat-auth`:

```bash
# Step 1: set up secrets
claude setup-token
echo 'export CLAUDE_CODE_OAUTH_TOKEN=<CLAUDE_CODE_OAUTH_TOKEN> >> ~/.agents/.env.global

# For anthropic-console seats:
mkdir -p ~/.agents/secrets/claude
echo 'ANTHROPIC_API_KEY=<ANTHROPIC_API_KEY> > ~/.agents/secrets/claude/anthropic-console.env
chmod 600 ~/.agents/secrets/claude/anthropic-console.env

# Step 2: preview
python3.11 core/scripts/migrate_seat_auth.py plan
python3.11 core/scripts/migrate_seat_auth.py apply --dry-run

# Step 3: apply
python3.11 core/scripts/migrate_seat_auth.py apply

# Step 4: restart seats to pick up new env
tmux kill-session -t install-koder-claude   # repeat for each seat
```

See also `docs/ARCHITECTURE.md §3j`.

## Host environment preservation (PROXY / TLS / Claude Desktop OAuth state)

> Added 2026-05-04 after the install-memory 403 investigation.

Claude OAuth seats (`oauth` and `oauth_token`) — and other claude-tool
seats started by `core/launchers/agent-launcher.sh` — historically wiped
all `ANTHROPIC_*` and `CLAUDE_CODE_*` env vars before launching to drop
stale provider state. That wipe was *too broad*: it also dropped
host-supplied state that OAuth seats genuinely need.

### What is now preserved

The `capture_oauth_host_env` helper in
`core/launchers/helpers/env.sh` snapshots the relevant vars *before*
the unset and restores them *after*. The whitelist:

| Var | Why preserved |
|-----|---------------|
| `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY` / `NO_PROXY` (and lower-case) | Required to reach `api.anthropic.com` on region-restricted networks (China etc.) — without it the seat hits transient `429`s that surface as `403 "Request not allowed"` while host Claude Desktop (which keeps PROXY) works fine. |
| `NODE_USE_SYSTEM_CA` / `NODE_EXTRA_CA_CERTS` | Corporate/system CA bundles. |
| `API_TIMEOUT_MS` | Long requests (compaction, large agent tasks) need 600s+. |
| `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST` + sibling `CLAUDE_CODE_*` markers (token, subscription tier, etc.) | Only preserved when `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST=1` is set on the host (Claude Desktop wrapper marker). The presence of the marker means the host already gave us a coherent OAuth env we should ride; absence means treat any inherited token as stale and drop it (preserves the original re-auth-on-stale-env safety). |

### What is still wiped (intentionally)

- `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`,
  `ANTHROPIC_MODEL` — wiped to prevent API-mode env from polluting the
  OAuth credential resolution path.
- `CLAUDE_CODE_OAUTH_TOKEN` *without* the `PROVIDER_MANAGED_BY_HOST=1`
  marker — wiped because anything in the env without the host marker
  could be a stale token from an older shell session.
- `BAGGAGE` (Sentry tracing) — not preserved across client boundaries.

### Symptoms that originally drove this

- install-memory (`oauth` host reuse) randomly returned
  `API Error: 403 {"error":{"type":"forbidden","message":"Request not allowed"}}`
  while host Claude Desktop on the same OAuth credential worked fine.
- Restarting the seat (`agent_admin session start-engineer ... --reset`)
  temporarily recovered.
- Claude Code CLI v2.1.126 maps several transient server states to the
  `403 "Request not allowed"` string, masking the real cause; the issue
  is tracked upstream in
  [anthropics/claude-code#53563](https://github.com/anthropics/claude-code/issues/53563)
  and [#53635](https://github.com/anthropics/claude-code/issues/53635).
- Even after this preservation, the upstream transient is not fully
  fixed — the seat recovery flow (`session start-engineer --reset`,
  which auto-refreshes the memories window via the hook in
  `agent_admin_session_lifecycle._auto_refresh_memories_window_after_memory_start`)
  remains the canonical workaround when 403 surfaces.
