# Seat Authorization Enforcement

cartooner-harness's [Skill Authorization Matrix](../SKILL.md#skill-authorization-matrix)
is enforced in **three layers**, each progressively more structural.
Higher layers shouldn't be relied on alone; the lower layers are the
guarantee.

| Layer | Where | Strength | Caught example |
|---|---|---|---|
| 1. Prose | `AGENTS.md` / `CLAUDE.md` / template | Soft (LLM compliance) | "memory should not draft lyrics directly" |
| 2. Audit | `patrol_pipeline_sla.py --check authorization` | Post-hoc detection | violation logged in `generation_log.jsonl` |
| 3. **Gate** | per-CLI `seat_gate.{mjs,py}` import + check | **Hard stop** | `node generate_song.mjs` exits 2 when `$CLAWSEAT_SEAT != builder-av` |

## Why three layers

### 1. Prose alone fails the convenience pull

LLM compliance is high but not absolute. When a "shortcut" presents
itself ("user is waiting; I have the API key; I have the binary; let me
just run it"), the model rationalizes. The 2026-05-11 cartooner-video
incident: memory ran `node <HOME>`
itself instead of dispatching to builder-av — and on reflection
acknowledged it knew the protocol but proceeded anyway.

### 2. Audit is post-hoc — too late to prevent the harm

`patrol_pipeline_sla.py` scans `generation_log.jsonl` and reports the
violation. Useful for accountability, but the asset has already been
generated, the bash command already ran, the API key already exposed
in tmux history.

### 3. Gate is structural — exits before any side effect

A 5-line preamble in each cartooner-* skill's CLI entry point reads
`$CLAWSEAT_SEAT` (set by ClawSeat's launcher per session.toml) and
exits 2 with a structured refusal payload if the seat is not in the
skill's authorized list. The bash subprocess fails immediately, no
generation, no API call, no asset on disk. Memory has no successful
path forward except dispatch.

## Authorization SSOT

[`scripts/seat_authorized_skills.json`](../scripts/seat_authorized_skills.json)
mirrors the table in `SKILL.md`. Adding a new cartooner-* skill or
moving a skill between seats requires updating this file AND at least
one source: SKILL.md (human-readable) and the per-CLI gate calls
(machine-enforced).

## Gate integration pattern

### Node-based skills (most cartooner-* skills)

`core/skills/cartooner-harness/scripts/seat_gate.mjs` — single helper.
At the very top of any CLI entry script:

```js
#!/usr/bin/env node
import { gate } from `${process.env.CLAWSEAT_ROOT || ""}/core/skills/cartooner-harness/scripts/seat_gate.mjs`;
gate({ skill: "cartooner-audio", allowed: ["builder-av"] });

// ...rest of the CLI
```

The gate is a no-op when `$CLAWSEAT_SEAT` is unset (e.g., operator
running the script directly from their shell for testing). Only fires
inside ClawSeat seat sandboxes where the env var is exported.

If `$CLAWSEAT_ROOT` is also unset (shouldn't happen for managed seats),
the import path is empty and Node fails loudly — fail-closed.

### Python-based skills

A `seat_gate.py` helper would mirror the same contract:

```python
from seat_gate import gate
gate(skill="cartooner-resource-ops", allowed=["memory", "patrol"])
```

Not yet shipped; add when needed.

### Shell-based skills

For pure-shell skill entries:

```bash
CLAWSEAT_SEAT="${CLAWSEAT_SEAT:-}"
ALLOWED=("builder-av")
if [ -n "$CLAWSEAT_SEAT" ] && ! printf '%s\n' "${ALLOWED[@]}" | grep -qx "$CLAWSEAT_SEAT"; then
  jq -n --arg seat "$CLAWSEAT_SEAT" --arg skill "<this-skill>" \
       --argjson allowed "$(printf '%s\n' "${ALLOWED[@]}" | jq -R . | jq -s .)" \
       '{ok:false,error:"SEAT_NOT_AUTHORIZED",seat:$seat,skill:$skill,allowed:$allowed,fix:"...spawn_lane.py..."}' >&2
  exit 2
fi
```

## Refusal payload schema

When a gate fires, stderr gets a single JSON line:

```json
{
  "ok": false,
  "error": "SEAT_NOT_AUTHORIZED",
  "seat": "memory",
  "skill": "cartooner-audio",
  "allowed": ["builder-av"],
  "fix": "seat \"memory\" cannot invoke cartooner-audio CLIs directly. Per cartooner-harness Authorization Matrix, only builder-av may produce this asset type. From memory's pane, dispatch with: spawn_lane.py --seat builder-av --count N --shot-id <id> --prompt <L2>"
}
```

The fix string names the canonical dispatch path so the offending
seat's model can self-correct. Exit code 2 distinguishes seat refusal
from other CLI errors (1 generic / 0 success / >2 reserved).

## What this does NOT enforce

- **Filesystem read** of asset content: no-image-policy is still soft.
  Memory could `cat` a deposited audio file as bytes; cooperation with
  no-image-policy is required.
- **API endpoint reach**: if a seat exports its own API key and uses
  `curl` directly to the model API endpoint (bypassing the cartooner
  CLI entirely), the gate doesn't intercept. Defense-in-depth via patrol
  audit + per-seat secret-file scope (only authorized seats get the
  relevant keys.env stub).
- **Cross-cartooner-* delegation**: builder-image invoking
  cartooner-audio's `generate_song.mjs` is also rejected — only
  `builder-av` is authorized.
