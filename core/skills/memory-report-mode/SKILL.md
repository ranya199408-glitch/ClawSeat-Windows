---
name: memory-report-mode
description: "Memory-only planner report mode: sender routing, AUTO reports, and goal-drift recall."
version: "1.0"
status: stable
---

# Memory Report Mode

Memory loads this skill in addition to `clawseat-intake`. It is only for
messages that come from planner or project-control channels, not for direct user
intake.

## Sender Routing

Route by sender metadata before interpreting content:

```text
sender == "user"    -> Clarify mode
sender == "planner" -> Report mode
sender unknown      -> Clarify mode
```

Channel only changes rendering. Claude/Codex/Gemini TUI uses concise Markdown;
Feishu recall cards may use native card controls through Koder.

## Report Mode

Planner updates become an AUTO decision report:

```text
[Action] [Reason 1 sentence]
```

Do not add preamble, ask approval, or write "I suggest". Memory acts as the
user's proxy and reports the current best action with the shortest defensible
reason.

Reference: `references/report-mode.md`

## Drift Detection

Interrupt AUTO reporting only when one of the four goal-drift signal families
crosses threshold:

- scope expansion after scope lock
- milestone delay beyond the planned threshold
- stale assumption about branch, dependency, tool, external API, or policy
- focus no longer maps to the north-star goal or accepted milestone

Recall cards have at most 3 options. Plain AUTO reports do not ask for approval.

References:

- `references/drift-signals.md`
- `references/tui-card-format.md`
- `references/north-star-schema.toml`

## Skill Boundary

- Koder does not load this skill.
- Planner does not load this skill.
- Memory loads this skill for planner updates and keeps `clawseat-intake`
  for direct user intake.
