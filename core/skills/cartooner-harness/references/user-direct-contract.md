# User Direct Contract

The `user` (Creator) may bypass `memory` and address any seat directly.
This document specifies the protocol contract that keeps `memory` in
sync as the project's single source of truth despite the bypass.

## What "user direct" means

The user types instructions into a seat's tmux pane (e.g., the
`builder-image` pane) without going through the memory pane. The seat
receives the instruction and executes it as if it had been dispatched by
memory.

This is **not** a side channel for hidden state. Every user-direct
action becomes part of the project's audit trail through mandatory
reporting.

## Why allow it

Real producers walk onto set and address the DP / Composer / Editor /
Writer / Data Wrangler directly. Going through the Line Producer for
every micro-instruction would be slow, formal, and unrealistic for the
high-iteration loop that creative work requires.

The cartooner-harness equivalent: user types "再来 4 张更暗的" into the
builder-image pane and gets candidates in seconds, instead of dictating
to memory who then formulates a spawn_lane.

## Allowed scope by seat

| Seat | Mutate | Query | Notes |
|---|---|---|---|
| memory | ✅ | ✅ | Default channel; no bypass needed but allowed |
| writer | ✅ | ✅ | "改这场对白", "重写 shot 3 narrative" |
| builder-image | ✅ | ✅ | "再来 4 张更暗", "用 nb2 不要 gpt-image-2", or "shot-5 改用 wide composition" |
| builder-av | ✅ | ✅ | "shot_list.toml shot-5 改 wide-shot", "BGM 换 ke", "Seedance 用 mode 7", or "ingest @youtube/wong-kar-wai/itmfl 用作 shot reference" |
| **patrol** | **❌** | ✅ | Patrol is read-only Asset Guardian. User may query SLA / integrity / index status, but **may not instruct patrol to modify any asset or state**. |

Mutate instructions to patrol return a clear error:

```
[patrol] Patrol is read-only per cartooner-harness contract. To modify
asset state, please address builder-image (for image assets) or
builder-av (for video/audio assets) directly. To re-trigger SLA / index
checks, you may call them as queries.
```

## Mandatory contract: `report_to_memory.py`

Any seat that receives a user-direct instruction **MUST** call
`report_to_memory.py` either before, during, or immediately after
execution. Choice depends on operation duration:

- **Quick operations** (< 5s, e.g., a query or single-asset deposit):
  report after completion is acceptable
- **Long operations** (≥ 5s, e.g., spawn_lane with multi-second
  generation, or reference-learning subagent ingesting a YouTube video):
  report **before** starting AND **after** completion

### Payload

```bash
report_to_memory.py \
  --project <project-id> \
  --event user_direct_request \
  --triggered-by user \
  --intent "再来 4 张更暗的, low-key lighting" \
  --seat builder-image \
  --action spawn_lane \
  --supersedes lane-img-042 \
  --child-lane lane-img-045
```

For subagent-using actions (root-cause / reference-learning):

```bash
report_to_memory.py \
  --project <project-id> \
  --event user_direct_request \
  --triggered-by user \
  --intent "ingest Wong Kar-wai for shot reference" \
  --seat builder-av \
  --action spawn_subagent \
  --subagent-type reference_learning \
  --subagent-inputs '{"url": "...", "focus": "shot rhythm"}'
```

### Fail-closed semantics

If `report_to_memory.py` exits non-zero, the seat **must abort** the
user-direct action. This is fail-closed: the protocol prefers no action
over an unrecorded action.

If memory is unreachable (its tmux pane crashed, its session is dead),
`report_to_memory.py` fails. The seat surfaces the failure to the user
through the seat's own pane:

```
[builder-image] cannot reach memory; cartooner-harness contract requires
all user-direct actions to be reported. Please re-establish memory
before proceeding, or use the memory pane directly.
```

This deliberately blocks. We do not allow stranded mutations.

## Conflict resolution: Producer wins

User-direct may conflict with an in-flight memory dispatch. Example:

```
[memory] just spawned lane-img-042 (4 close-ups for shot-1)
[user, 1s later, in builder-image pane] "stop, I want wide shots
instead, 6 of them"
```

Resolution rule: **Producer always wins**. The seat:

1. Calls `report_to_memory.py --supersedes lane-img-042` to mark the
   pending lane as superseded
2. Spawns the new lane per the user-direct instruction
3. The original lane completes any in-flight generations and deposits
   them with `state=orphan` flag in PROJECT_INDEX (so tournaments
   exclude them but the work isn't lost)
4. Memory receives the supersession notice and updates its state
   accordingly; subsequent `pick_winner` for shot-1 r1 is cancelled

If memory had already started consuming partial output (e.g., started a
downstream `spawn_lane builder-av` based on a not-yet-picked image), it
also rolls back / supersedes the downstream lane.

## What memory must do on receipt

When `report_to_memory.py` arrives, memory:

1. Validates the report: target seat, action type, supersedes references
2. Updates `PROJECT_INDEX.json` to reflect new lane / asset / pick state
3. Appends to `generation_log.jsonl` with `triggered_by = "user_direct"`
   and `actor = "user"` so audit shows the producer's footprint
4. Cancels / supersedes any conflicting pending memory-initiated work
5. Notifies any downstream-dependent seat (e.g., if writer was waiting
   for memory's instruction and the producer instructed builder-image
   instead, writer is told to standby)
6. Auto-flips automation mode to manual if currently in auto (because
   user_direct_received is an escalation trigger)
7. Returns success to the calling seat

If validation fails (bad payload, unknown seat, malformed supersedes),
memory returns error and the seat aborts (fail-closed).

## Subagent flows under user-direct

### Root-cause subagent (user feedback triggers)

```
[user → builder-image pane]: "all 4 are too bright"
↓
builder-image:
  1. report_to_memory.py --event user_direct_request \
       --triggered-by user --seat builder-image \
       --intent "all 4 too bright" --action spawn_subagent \
       --subagent-type root_cause
  2. spawn root-cause subagent (use spawn_subagent.py for the v2 hardened
     contract; subagent runs in isolated context):
     - vision input: 4 candidate paths
     - subagent analyzes brightness pattern
     - returns text root-cause report
  3. main thread receives text only
  4. adjust L3 prompt based on text report
  5. spawn_lane re-spawn (a new lane, with parent-lane = lane-img-042,
     triggered-by = user_direct, actor = builder-image)
  6. report_to_memory.py --event lane_completed --child-lane <new-id>
↓
memory: updates PROJECT_INDEX, generation_log carries full provenance
```

### Reference-learning subagent (user provides reference URL)

```
[user → builder-av pane]:
  "ingest @youtube/wong-kar-wai/in-the-mood-for-love for shot rhythm
   reference, then revise shot_list"
↓
builder-av:
  1. report_to_memory.py --event user_direct_request \
       --triggered-by user --seat builder-av \
       --intent "learn from WKW ITMFL for shot rhythm" \
       --action spawn_subagent --subagent-type reference_learning \
       --subagent-inputs '{"url": "...", "focus": "shot rhythm"}'
  2. spawn reference-learning subagent (isolated, Gemini):
     - YouTube URL ingest
     - subagent extracts shot rhythm patterns
     - returns text shot-analysis report
  3. main thread receives text only; report saved to
     ~/.cartooner/projects/<id>/references_learned/wong-kar-wai-itmfl.md
  4. revise shot_list.toml integrating reference findings
  5. report_to_memory.py --event shot_list_revised --version v2
↓
memory: updates PROJECT_INDEX (shot_list version bump), invalidates any
        downstream lanes referencing shot_list@v1, escalates to user for
        re-approval of shot_list v2
```

In both cases:
- main thread context remains image-free per no-image-policy
- subagent context is discarded after return
- audit trail captures the user-direct trigger + subagent invocation +
  resulting state changes

## What user-direct does NOT allow

- **Direct write to PROJECT_INDEX.json**: only memory and `deposit_asset`
  may write the index. User-direct goes through the seat, the seat goes
  through deposit_asset / report_to_memory, which write the index.
- **Skipping style_bible**: user-direct prompts still apply
  style_bible.md unless the user explicitly overrides via
  `--ignore-style-bible` flag (which is logged loudly).
- **Picking on behalf of patrol**: patrol cannot mutate, period.
- **Bypassing automation_mode escalation rules**: user_direct
  automatically flips to manual mode (it's an escalation trigger),
  even if user wanted to remain in auto.
- **Subagent recursion**: user cannot instruct a seat to "have a
  subagent spawn another subagent". Flat hierarchy enforced.
- **Vision input passed back to main thread**: even via user-direct,
  no-image-policy stands. User cannot say "memory, look at this image
  and tell me what's wrong" — memory will respond with a refusal and
  redirect user to builder-image (with root-cause subagent path).

## Example trace (full path)

```
[manual mode]
[user types in builder-image pane]
"忽略最近的 lane，再来 6 张广角，用 gpt-image-2，黄昏光"

[builder-image, before executing]
report_to_memory.py \
  --project <project-id> \
  --event user_direct_request \
  --triggered-by user \
  --intent "ignore latest lane, 6 wide shots, gpt-image-2, golden hour" \
  --seat builder-image \
  --action spawn_lane \
  --supersedes lane-img-042

[memory]
- marks lane-img-042 as superseded
- cancels pending pick_winner for tournament-shot-1-r1
- writes generation_log entry with triggered_by=user_direct
- returns OK to builder-image

[builder-image]
spawn_lane.py \
  --project <project-id> \
  --seat builder-image \
  --actor builder-image \
  --triggered-by user_direct \
  --count 6 \
  --shot-id shot-1 \
  --parent-lane lane-img-042 \
  --prompt "wide shot, gpt-image-2, golden hour"
# (model + style aspect are inlined in --prompt; spawn_lane has no
#  --override-model / --override-style-aspect flags. The seat decides
#  the L3 syntax when it processes the lane.)

[builder-image, after generation]
deposit_asset.py × 6 (img-051 ... img-056) — model_metadata + file_metadata only
report_to_memory.py \
  --project <project-id> \
  --event lane_completed \
  --triggered-by user \
  --seat builder-image \
  --child-lane lane-img-051

[memory]
- updates PROJECT_INDEX
- creates new tournament-shot-1-r2 with the 6 candidates
- since manual mode (auto-flipped on user_direct_received), waits for user pick
- prints to memory pane: "6 wide shots ready in tournament-shot-1-r2, awaiting pick"

[user, in memory pane]
pick_winner --round tournament-shot-1-r2 --winner img-053

[memory]
- records pick
- generation_log entry
- ready to advance to next phase / next lane
```

Note that even though the user bypassed memory at the entry, memory ends
up fully informed and remains the project's coordination authority.
That is the contract.
