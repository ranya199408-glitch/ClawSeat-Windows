# OpenClaw Skill Install Protocol (2026-04-30 BJ)

## Trigger

`install.sh` detects an existing `~/.openclaw` directory and mirrors the
OpenClaw-facing ClawSeat skills automatically.

## Mirror Whitelist

- `clawseat-intake`
- `clawseat-koder`

Other ClawSeat skills are not mirrored into OpenClaw. OpenClaw agents should
use progressive disclosure and load only the bridge skills they need.

## Mirror Mechanism

`install_skills_by_tier` calls:

```bash
install_skill_tier_for_home openclaw "$HOME/.openclaw/skills" \
  "clawseat-intake" "clawseat-koder"
```

The link target remains the ClawSeat SSOT under `~/.agents/skills/`; OpenClaw
gets symlinks such as:

```text
~/.openclaw/skills/clawseat-intake -> ~/.agents/skills/clawseat-intake
```

## Per-Agent Activation

No per-agent activation is performed. OpenClaw agents such as cartooner, koder,
main, mor, and yu decide at runtime whether to use these skills.

## Manual Backfill

If OpenClaw is installed after ClawSeat, the operator may run reinstall or
manually backfill:

```bash
ln -sfn "$HOME/.agents/skills/clawseat-intake" "$HOME/.openclaw/skills/clawseat-intake"
ln -sfn "$HOME/.agents/skills/clawseat-koder" "$HOME/.openclaw/skills/clawseat-koder"
```

## Reverse Sync

Reverse sync from OpenClaw to ClawSeat is not allowed. ClawSeat is the SSOT;
OpenClaw is only a mirror endpoint. To change a bridge skill, edit the
ClawSeat `core/skills/.../SKILL.md` source and run install/reinstall to refresh
the mirror.
