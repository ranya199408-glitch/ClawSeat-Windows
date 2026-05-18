# Lane Model

`lane` is the atomic unit of work in cartooner-harness, distinct from
gstack-harness's `task`. A lane represents one generation thread (image /
video / audio) that **may produce multiple candidates** in parallel.

## Why `lane`, not `task`

A `task` (engineering chain) presupposes a single correct outcome:
implement function `X`, fix bug `Y`. The reviewer either approves or
requests changes.

A creative request is fundamentally different: "draw an apple" has no
single correct outcome. The Producer wants to **see options** and pick.
Even after picking, the chosen output may need iteration ("more shadow",
"shift hue") — each iteration may itself produce multiple candidates.

`lane` captures this: a generation thread that **may produce N candidates**
in parallel, on a single seat, for a single shot.

## Lane states

```
spawned ──┬──▶ generating ──┬──▶ deposited ──▶ picked
          │                  │
          │                  └──▶ failed (api error / deposit failure)
          │
          └──▶ superseded (user-direct or memory cancelled the lane)
```

| State | Meaning | Who transitions |
|---|---|---|
| `spawned` | `spawn_lane.py` called; seat acknowledged but not started | spawn_lane |
| `generating` | seat is calling cartooner-image / -video / -audio API | seat (auto) |
| `deposited` | one or more assets persisted into PROJECT_INDEX | deposit_asset |
| `picked` | a candidate from this lane was selected by `pick_winner` | pick_winner |
| `failed` | generation errored (api fail / deposit fail / SLA breach) | seat (auto) |
| `superseded` | a newer user-direct or memory request replaced this lane | report_to_memory --supersedes |

A lane never goes from `picked` back to other states. Iteration creates a
**new lane** with `parent_lane` ref, not a rewind.

## Lane payload (lanes/<lane-id>.toml)

```toml
id = "lane-img-042"
created_at = "2026-05-10T15:00:00Z"
state = "deposited"
seat = "builder-image"

# Cross-modal join key
shot_id = "shot-1"          # references shot_list.toml; required for builder-image / builder-av
                            # null/absent for non-shot-bound work (e.g., calibration, BGM)

# Concurrency
count = 4                   # number of concurrent generations on this seat

# Inputs
shot_list_ref = "shot_list.toml@v3"
style_bible_ref = "style_bible.md@v2"
character_dna_ref = "character_dna.json@v1"   # optional
input_image_asset = "img-002"                 # for i2v lanes

# Provenance
parent_lane = "lane-img-041"                   # if iterating
triggered_by = "memory_spawn"                  # memory_spawn | user_direct | iterate_prompt | auto_iterate

# Per-candidate prompts (L3, written by the seat itself)
[[candidates]]
asset_id = "img-042-a"
model = "nano-banana"
prompt = "<L3 model-specific prompt>"
seed = 12345
status = "deposited"

[[candidates]]
asset_id = "img-042-b"
model = "nano-banana"
prompt = "<L3 model-specific prompt>"
seed = 12346
status = "deposited"

# ... up to count

[result]
candidates = ["img-042-a", "img-042-b", "img-042-c", "img-042-d"]
deposited_at = "2026-05-10T15:00:42Z"
generation_log_entries = ["log-1023", "log-1024", "log-1025", "log-1026"]
```

The `count` field is the most important departure from gstack-harness:
**creative dispatch fans out by default**. The Producer rarely wants one
take of one shot; they want options.

The `shot_id` field is the cross-modal join key. Multiple lanes (image
lane + video lane + audio lane) all referencing `shot_id="shot-1"` work
on the same shot's deliverables.

## Lane-on-seat semantics

Multiple lanes may run on the same seat concurrently. Example:

```
memory: spawn_lane(seat=builder-image, shot_id="shot-1", count=4)
memory: spawn_lane(seat=builder-image, shot_id="shot-2", count=4)
```

builder-image now has 8 generations queued (4 for shot-1 + 4 for shot-2).
It processes them in parallel where the underlying API permits, otherwise
serially. The **lane boundary** ensures candidates don't get mixed up
across shots — `shot_id` is the key for grouping.

## Self-dispatch (user-direct fast path)

When the user talks directly to a seat:

```
user → builder-image: "再来 4 张更暗的"
```

builder-image may **self-dispatch**: it calls
`spawn_lane.py --self --count 4 --triggered_by user_direct
--parent_lane <last>` on itself, after first calling `report_to_memory.py`
to record the user-direct event (fail-closed).

The lane record carries `triggered_by = "user_direct"` so memory and
audit can distinguish self-dispatched lanes from memory-orchestrated ones.

## Lane vs Tournament

A `lane` produces candidates. A `tournament` selects from candidates,
possibly drawing from multiple lanes:

```
lane-img-042 (shot-1, 4 candidates)  ─┐
                                       ├─▶ tournament-shot-1-r1 (8 candidates)
lane-img-043 (shot-1, 4 alt cands.)  ─┘     user picks 1 (or memory auto-picks via metadata-rank)
```

memory aggregates lane outputs into a tournament before calling
`pick_winner`. Tournaments are joined by `shot_id`: all lanes for the
same shot feed into the same tournament round.

## deposit_asset payload (no LLM self-eval)

When a lane completes, the seat calls `deposit_asset.py` per candidate.
Per [no-image-policy](no-image-policy.md), deposits do **NOT** include LLM
self-evaluations:

```toml
asset_id = "img-042-a"
asset_path = "~/.cartooner/projects/<id>/assets/images/img-042-a.png"
lane_id = "lane-img-042"
shot_id = "shot-1"

[generation]
seat = "builder-image"
model = "nano-banana"
prompt = "<L3 prompt>"
seed = 12345
api_status = "200"
generated_at = "2026-05-10T15:00:42Z"

[file_metadata]
size_bytes = 1843200
dimensions = "1024x1024"
format = "png"
sha256 = "abc..."

[model_metadata]
# Only what the model itself returns, never LLM judgment
aesthetic_score = 0.81      # if provided by the model
safety_score = 1.0          # if provided
confidence = 0.93           # if provided

[provenance]
triggered_by = "memory_spawn"   # or user_direct / iterate_prompt / auto_iterate
parent_lane = null              # or <ancestor lane id>
shot_list_ref = "shot_list.toml@v3"
style_bible_ref = "style_bible.md@v2"
```

Forbidden fields:
- `self_eval` (any LLM-generated quality assessment)
- `style_compliance_score` (any LLM judgment of style match)
- `image_thumbnail` / `preview_base64` (any embedded image bytes)

## Lane lifecycle constraints

- A lane MUST be `spawned` before `generating` (no unsolicited generation)
- A lane MUST `deposit_asset` for each candidate before transitioning to
  `deposited` (no half-deposits; either all candidates land or the lane
  is `failed`)
- A lane in `superseded` state still completes any in-flight generation
  and deposits assets, but flags them as `orphan` in PROJECT_INDEX so
  tournaments do not include them
- A lane in `picked` state may **not** be re-picked; iterate creates a
  child lane with `parent_lane = <picked-lane>`
- Every lane has either a `shot_id` (image / video / per-shot audio) or
  is explicitly marked as project-level work (calibration / BGM /
  reference learning)
