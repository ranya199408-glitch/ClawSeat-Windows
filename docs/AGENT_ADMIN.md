# Agent Admin reference

## rebind vs delete+create

| Action | What changes | What stays | Use when |
|--------|--------------|------------|----------|
| `engineer rebind <id> <mode> <provider>` | auth_mode, provider (→ identity rename, runtime dir, template re-apply) | tool, engineer_id, workspace, session.toml location | Switch between oauth/api or provider variants (anthropic ↔ bedrock) on the **same tool**. |
| `engineer delete <id>` + `engineer create ...` | Everything (tool, identity, runtime, session.toml) | Project binding (need to re-create under same project) | Switching **tool** (e.g. claude → codex), since rebind can't migrate tool-specific runtime. |

### Why rebind cannot change tool

`session.tool` drives identity name, runtime dir, template selection, and credential path layout — changing it in-place would strand archived state and invalidate the template-rendered files. `engineer rebind` intentionally rejects `--tool` mismatches via exit code 2 (see `CrudCommands.engineer_rebind`).

### Signals

- `rebind` exit code 0 → success
- `rebind` exit code 2 → user error (tool mismatch); stderr explains
- `rebind` exit code 1 → generic failure (preserves existing behavior)
