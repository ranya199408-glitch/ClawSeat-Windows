# Automation Mode

cartooner-harness supports two modes for `memory`'s coordination authority:
**manual** (default) and **auto**. The toggle is the user's primary lever
for trading involvement against speed.

**Critical clarification**: Auto mode is a **process-automation engine**,
not a creative-decision engine. memory in auto mode never makes aesthetic
judgments. All creative decisions either escalate to user or use
model-provided numeric scores (when configured).

## Mode toggle

`set_automation_mode.py --mode manual|auto [--pick-strategy <name>]
[--escalate-on <comma-list>]`

Stored inside `PROJECT_INDEX.json` (no separate `automation.toml`):

```json
{
  "automation_mode": "manual",
  "automation_config": {
    "mode": "manual",
    "set_at": "2026-05-10T15:30:00Z",
    "set_by": "user",
    "triggered_by": null,
    "pick_strategy": "escalate-always",
    "escalate_on": [
      "lane_failure",
      "sla_breach",
      "phase_transition",
      "budget_exhausted",
      "tournament_ready_no_auto_pick_strategy",
      "user_direct_received",
      "seat_authorization_violation",
      "vision_spec_violation",
      "subagent_failure"
    ]
  }
}
```

`pick_strategy` and `escalate_on` are only present when mode is `auto`.
Budget and undo-window settings are not yet implemented at the script
level — when added they will land alongside `automation_config`, not in
a separate file.

## Manual mode (default)

In manual mode:

- **memory** is Vision Steward (process automation only); never picks or
  iterates without user input
- **user** is active Creator (Producer + Director)
- `pick_winner` always blocks on user input (UI: tournament view in tmux
  pane or 飞书 push with image links)
- `iterate_prompt` requires user to articulate L1/L2/L3 intent; memory
  routes but never invents iteration direction
- No memory-initiated decisions are made without user instruction

This is the safe default. New projects start in manual mode.

## Auto mode (process-automation engine)

User explicitly opts in: `set_automation_mode.py --mode auto`.

Memory may automatically perform mechanical / rule-driven actions:

| Action | When | How |
|---|---|---|
| Spawn next lane | Per `vision_spec.md` plan; previous phase completed | spawn_lane.py |
| Transition lane state | API status / file checks | spawned → generating → deposited |
| Aggregate tournament | Lanes complete with same `shot_id` | Build tournament round |
| Auto-pick (rare) | Only when `pick_strategy = "model-metadata-rank"` AND model provides `aesthetic_score` | rank by score; threshold gated |
| Trigger phase transition | `vision_spec` + lane completion criteria met | Spawn next phase's lanes |
| Update `progress_report.md` | After every significant event | Append text log |
| Escalate to user | Any escalation condition fires | escalate_to_producer.py |

Memory **never**:
- Views asset content (no-image-policy is hard rule, not mode-dependent)
- Picks based on visual aesthetic judgment
- Auto-picks when no `model-metadata-rank` strategy is configured (default
  triggers `tournament_ready_no_auto_pick_strategy` escalation)
- Auto-iterates without user feedback (no LLM-guessed iteration direction)
- Changes L1 (brief / style_bible / vision_spec) without explicit user
  authorization
- Skips audit log
- Declines to escalate when a trigger fires

## `pick_strategy` options

| Strategy | Behavior | When to use |
|---|---|---|
| **`escalate-always`** (default) | Tournament ready → escalate to user; never auto-pick | Default; no aesthetic judgment without user |
| `model-metadata-rank` | Rank by model-provided `aesthetic_score`; pick highest above `min_score` threshold; if none above threshold, escalate | Model provides scores AND user explicitly opts in |
| `first-passing` | First candidate where `api_status == 200` AND file checks pass; reject `failed` candidates only | When user wants throughput over quality (rare) |
| `random-from-passing` | Random pick among passing candidates | A/B testing / exploration only |

Notably **NOT** an option:
- `llm-judge` — would require memory to view images; explicitly forbidden
- `style-compliance-rank` — would require LLM visual judgment; forbidden

If `pick_strategy != escalate-always` and the strategy fails to find a
qualifying candidate, fallback is **always** escalate to user.

## Escalation triggers (mechanically defined)

| Trigger | Definition | Why escalate |
|---|---|---|
| `lane_failure` | API error, deposit failure, or all candidates marked `failed` | Cannot produce output; need human decision |
| `sla_breach` | `patrol` detected pipeline degradation (provider success rate below threshold) | Cannot produce reliable output; user decides whether to wait, switch, pause |
| `phase_transition` | Crossing major phase boundaries (script → image → video → audio → integration) | High-stakes; default to user checkpoint |
| `budget_exhausted` | Token cap or wall-clock minutes hit | Resource bound; user decides extend / accept / abort |
| `tournament_ready_no_auto_pick_strategy` | Candidates ready but pick_strategy is `escalate-always` (default) | The expected case — auto mode advances state, user picks |
| `user_direct_received` | User addressed any seat directly | Auto-flip to manual; user is back |
| `vision_spec_violation` | Auto action would violate `vision_spec.md` rule (e.g., trying to enter image phase before script lock) | Spec guardrail |
| `subagent_failure` | Root-cause or reference-learning subagent errored or returned malformed report | Cannot proceed without subagent output |
| `seat_authorization_violation` | `patrol_pipeline_sla.py --check authorization` detected a seat invoking a skill outside its authorized list (per Skill Authorization Matrix in cartooner-harness/SKILL.md) | Out-of-protocol behavior; user must investigate cause (drift / hallucination / config bug) before continuing |

User may add custom triggers in `escalate_on`. Removing default triggers
requires `--force-escalate-policy` (we do not silently allow risky
configurations).

Triggers explicitly **NOT** in this list (and why):
- `style_drift_exceeds_X` — would require LLM judging style visually
- `all_candidates_rejected_by_quality` — would require LLM judging quality
- `aesthetic_floor_breached` — would require LLM judging aesthetics

These all violate no-image-policy. Style / quality / aesthetic concerns
escalate via the user picking (or rejecting all candidates), not via
auto-detection.

## Audit log

Every auto decision writes to `generation_log.jsonl`:

```jsonl
{
  "ts": "2026-05-10T15:42:11Z",
  "event": "auto_pick",
  "mode": "auto",
  "actor": "memory_vision_steward",
  "round": "tournament-shot-1-r1",
  "strategy": "model-metadata-rank",
  "winner": "img-042-a",
  "winner_aesthetic_score": 0.87,
  "alternatives": [
    {"id": "img-042-b", "aesthetic_score": 0.74},
    {"id": "img-042-c", "aesthetic_score": 0.81},
    {"id": "img-042-d", "aesthetic_score": 0.69}
  ],
  "min_score_threshold": 0.75,
  "reasoning": "img-042-a had highest aesthetic_score (0.87) above threshold (0.75); other 3 reviewed; alternatives c (0.81) and b (0.74 — below threshold) noted",
  "undo_available_until": "2026-05-10T16:12:11Z"
}
```

Note: `reasoning` here is **memory's text reasoning** about its own
mechanical rule application, not visual judgment. It explains the rule
applied, not what the image looks like.

## Undo (planned, not yet implemented)

A future `undo_auto_decision.py` will let user revert any auto decision:

- The pick (or transition / spawn) is reverted
- Tournament state is restored to "awaiting pick"
- All downstream work that depended on the reverted decision is marked
  `superseded` (downstream lanes / assets / next-phase spawns)
- User is prompted to make the decision manually

For v1 the workflow is: user calls
`report_to_memory.py --supersedes <lane-id>` for the in-flight artifact
they want to redo, then re-spawns the lane with adjusted prompt. The
audit trail already supports the supersession; only the convenience
wrapper is pending.

## Auto mode in practice

```
[user, manual mode]
"建立项目，brief: 30s 红苹果广告，国风暗黑"
→ memory drafts brief.md, vision_spec.md, style_bible.md
→ user reviews, approves all three

[user]
"我要去吃饭，把 narrative_outline 和 shot_list 跑出来再叫我"
→ set_automation_mode.py --mode auto \
    --escalate-on lane_failure,sla_breach,phase_transition,budget_exhausted,tournament_ready_no_auto_pick_strategy

[memory, auto mode]
spawn_lane writer → narrative_outline.md draft v1
[lane completed → phase_transition trigger fires!]

→ escalate_to_producer "narrative draft ready, user review needed before
  shot_list phase"
→ memory mode flips to manual (spec policy: phase_transition always
  pauses)
→ 飞书 push with link to narrative_outline.md

[user 回来]
reviews narrative, approves
"OK, 进入 shot_list 阶段，自动跑到 shot_list 完成再 escalate"

[user]
set_automation_mode.py --mode auto

[memory, auto mode]
spawn_lane builder-av (STAGE 1) → shot_list.toml v1
[builder-av may invoke reference-learning subagent for shot grounding]
[lane completed → phase_transition trigger fires]

→ escalate_to_producer "shot_list ready, user review needed before image
  phase"
→ 飞书 push

[user reviews shot_list, gives one feedback]
"shot 5 改 wide-shot"

[memory, manual mode] (auto-flipped because user_direct_received)
iterate_prompt.py --layer L2 --target shot_list --parent-shot shot-5 \
  --feedback "shot-5 change to wide-shot"

[builder-av revises shot_list v2]
[user approves shot_list v2]

"再进 image phase，自动跑，每个 tournament ready 时 escalate"

[memory, auto mode again]
spawn_lane builder-image × 5 shots, count=4 each = 20 lanes
[lanes complete → 5 tournament rounds ready]
→ escalate × 5 (one per shot's tournament)

[user picks each shot's image]
[continues...]
```

The Producer's involvement is high-touch at boundaries
(phase_transitions, picks), hands-off in the interior (spawning,
state transitions, metadata maintenance). This is the value
proposition.

## What auto mode is NOT

| Misconception | Reality |
|---|---|
| "memory in auto mode acts as Director" | No — memory is process-automation engine; user remains the only Director |
| "memory will auto-pick using LLM judgment" | No — only `model-metadata-rank` (numeric scores from generation models) is allowed |
| "memory will auto-iterate when output looks bad" | No — iteration requires user feedback; memory never guesses iteration direction |
| "auto mode means user can leave for hours" | Yes for routine work, but escalations bring user back at every phase boundary |
| "auto mode handles style drift" | No — drift detection requires visual judgment which memory cannot do |
| "auto mode is for replacing the Producer" | No — for offloading mechanical drudgery; Producer remains essential |
