# ClawSeat agent launchers

Deterministic tmux-first launchers for Claude Code, Codex, and Gemini CLI.
The launcher layer is now agent-friendly by default:

- no AppleScript
- no GUI window management
- no interactive prompts
- explicit CLI args in, reproducible tmux/runtime state out

The code originally lived on `~/Desktop/`; merged into ClawSeat so every
install has a consistent entry point and operators do not have to keep
personal copies in sync.

## Files

| File | Purpose |
|------|---------|
| `agent-launcher.sh` | Main unified launcher — validates explicit CLI inputs, creates/reuses tmux sessions, and prepares isolated runtime homes. |
| `agent-launcher-common.sh` | Shared deterministic helpers: launcher state path, recent-dir tracking, directory normalization, slug generation. |
| `agent-launcher-discover.py` | API-key discovery across env vars / secret files for claude / codex / gemini. |
| `claude.sh` | Thin wrapper → `agent-launcher.sh --tool claude`. |
| `codex.sh` | Thin wrapper → `agent-launcher.sh --tool codex`. |
| `gemini.sh` | Thin wrapper → `agent-launcher.sh --tool gemini`. |

## Invocation

```bash
# Via wrapper (common case)
"$HOME/ClawSeat"/core/launchers/claude.sh \
    --auth oauth_token \
    --session install-planner-claude \
    --dir "$HOME/ClawSeat"

# Via repo-local root shim (standalone checkout)
"$HOME/ClawSeat"/claude-minimax.command \
    --auth oauth_token \
    --session install-planner-claude \
    --dir "$HOME/ClawSeat"

# Directly
"$HOME/ClawSeat"/core/launchers/agent-launcher.sh \
    --tool claude \
    --auth oauth_token \
    --session install-builder-1-claude \
    --dir ~/.clawseat

# tmux-only (the launcher no longer opens iTerm/Terminal windows)
~/.clawseat/core/launchers/agent-launcher.sh \
    --tool claude \
    --auth oauth_token \
    --session X \
    --dir "$HOME/ClawSeat" \
    --headless

# Dry-run (print resolved launch config, do not spawn)
~/.clawseat/core/launchers/agent-launcher.sh \
    --tool claude \
    --auth oauth_token \
    --dir "$HOME/ClawSeat" \
    --dry-run
```

`--headless` is retained as a compatibility flag for existing callers, but
the launcher is tmux-only regardless. `scripts/install.sh` and `agent_admin`
already treat the launcher as an internal L3 primitive and open or focus
visible panes separately when needed. The old direct primary-seat launch helper
has been removed; it is not the canonical fresh-install entry.

## Configuration (env vars)

The launcher is portable — no hard-coded `<HOME>` paths. Some legacy matcher
and compatibility settings remain env-driven:

| Env var | Default | Purpose |
|---------|---------|---------|
| `CLAWSEAT_LAUNCHER_ROOTS` | `~/coding:5, ~/Desktop/work:4, ~/Desktop:3, ~/Documents:3` | Compatibility roots for the deterministic matcher utility |
| `CLAWSEAT_LAUNCHER_FAVORITES` | `~/coding/cartooner, ~/coding/openclaw, ~/Desktop/work, ~/Desktop, ~/Documents, ~` | Compatibility favorites for the deterministic matcher utility |
| `AGENT_LAUNCHER_CUSTOM_PRESET_STORE` | `~/.config/clawseat/launcher-custom-presets.json` | Legacy custom preset store path; preserved for migration compatibility |
| `LAUNCHER_STATE_STORE` | `~/.config/clawseat/launcher-state.json` | Recent-directory / selection history |
| `AGENT_LAUNCHER_DISCOVER_HOME` | `$HOME` | Alternate home for key discovery (useful for runtime isolation testing) |

## Deterministic Contract

The launcher no longer prompts for missing inputs. Callers must provide:

- `--tool`
- `--auth`
- `--dir` or rely on the current working directory
- `--session` or accept the deterministic default `<tool>-<auth>-<basename(dir)>`

For `--auth custom`, callers must provide either:

- `--custom-env-file <path>`
- or `LAUNCHER_CUSTOM_API_KEY` in the environment, with optional
  `LAUNCHER_CUSTOM_BASE_URL` / `LAUNCHER_CUSTOM_MODEL`

The launcher always:

- creates or reuses the tmux session
- prepares the isolated runtime home
- prints manual `tmux attach` instructions

It never:

- opens iTerm / Terminal
- pops auth or directory dialogs
- reads interactive input

## Migration from `~/Desktop/` version

The desktop scripts (`~/Desktop/agent-launcher.command` etc.) continue to work
until you delete them. The ClawSeat version is authoritative going forward.
To migrate cleanly:

```bash
# Optional: backup the legacy desktop version
tar czf ~/desktop-launcher-backup.tgz ~/Desktop/.agent-launcher-* ~/Desktop/agent-launcher.command

# Replace desktop scripts with thin shims that delegate to clawseat
cat > ~/Desktop/agent-launcher.command <<'SHIM'
#!/usr/bin/env bash
set -euo pipefail
exec "$HOME/.clawseat/core/launchers/agent-launcher.sh" "$@"
SHIM
chmod +x ~/Desktop/agent-launcher.command

# Same pattern for claude-minimax.command / codex.command / gemini.command
# ...
```

Not doing the migration is OK — the legacy desktop store paths
(`~/Desktop/.agent-launcher-{state,custom-presets}.json`) are honored as a
fallback so no state is lost.

For standalone testing against a specific checkout such as `$HOME/ClawSeat`,
you can also point the desktop shims at the repo-local root wrappers
(`$HOME/ClawSeat/agent-launcher.command`, `$HOME/ClawSeat/codex.command`,
`$HOME/ClawSeat/gemini.command`, `$HOME/ClawSeat/claude-minimax.command`)
instead of routing through `~/.clawseat`.

## Related

- `core/scripts/iterm_panes_driver.py` — window layout driver used by higher
  layers that choose to open visible panes after tmux seats are running.
- `docs/INSTALL.md` — the v0.7 install playbook that routes fresh install
  through `scripts/install.sh`.
- `core/skills/clawseat-install/SKILL.md` — the install contract for agents.
