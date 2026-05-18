# Dispatch Intent Map

Use `--intent <KEY>` with `dispatch_task.py` to auto-inject the canonical gstack skill
trigger phrase into `--objective` AND append the skill's `SKILL.md` path to `--skill-refs`.

Without `--intent`, the target seat runs on default AI behaviour — the gstack methodology
(ship workflow, QA test-fix-verify loop, etc.) will NOT activate.

## Target Seat → Recommended `--intent` Key

| Target seat | Typical work | Recommended `--intent` key(s) |
|---|---|---|
| `builder-1` | Implementation, ship a PR | `ship`, `land`, `investigate`, `freeze`, `unfreeze` |
| `reviewer-1` | Pre-landing PR review | `code-review` |
| `patrol-1` | Test / bug-hunt a web app | `gstack-qa`, `gstack-qa-only`, `gstack-browse` |
| `designer-1` | Design audit / finalize UI | `design-critique`, `design-html`, `design-shotgun` |

For plan-phase intents (planner's own skills):

| Intent key | Activates |
|---|---|
| `eng-review` | gstack-plan-eng-review (architecture / data flow / test coverage) |
| `ceo-review` | gstack-plan-ceo-review (scope expand / hold / reduce) |
| `design-review` | gstack-plan-design-review (UX / visual / component) |
| `devex-review` | gstack-plan-devex-review (developer experience audit) |

Cross-cutting intents (any seat):

| Intent key | Activates |
|---|---|
| `office-hours` | gstack-office-hours (brainstorm / forcing questions / design doc) |
| `checkpoint` | gstack-checkpoint (save/resume working state) |

## Skills Mounted Per Seat (read-only reference)

Only activate skills the target seat actually has:

- `builder-1`: gstack-ship, gstack-land-and-deploy, gstack-investigate, gstack-freeze, gstack-unfreeze, gstack-browse, gstack-careful, gstack-checkpoint
- `reviewer-1`: gstack-review, gstack-browse, gstack-careful
- `patrol-1`: gstack-qa, gstack-qa-only, gstack-browse
- `designer-1`: gstack-design-html, gstack-design-review, gstack-design-shotgun, gstack-browse

Sending `--intent design-critique` to `builder-1` will NOT work — that skill is not on that seat.

## If No Intent Fits

Omit `--intent` and state the reason clearly in `--objective`. Use this for pure planning
or routing tasks without a corresponding gstack skill.
