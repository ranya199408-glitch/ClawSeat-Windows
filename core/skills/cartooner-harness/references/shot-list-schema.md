# shot_list.toml Schema

`shot_list.toml` is the L2b artifact: structured cinematic metadata
authored by `builder-av` (AV Cinematographer). Each shot is a TOML table
with cross-modal join key (`id`) and per-shot decisions.

## File location

`~/.cartooner/projects/<project-id>/shot_list.toml`

## Top-level fields

```toml
version = 1
project_id = "<project-id>"
narrative_ref = "narrative_outline.md@v3"
style_bible_ref = "style_bible.md@v2"
character_dna_ref = "character_dna.json@v1"  # optional
authored_at = "2026-05-10T16:30:00Z"
authored_by = "builder-av"

# Reference learning audit (subagent text reports that informed this draft)
references_learned = [
  "references_learned/wong-kar-wai-itmfl.md",
  "references_learned/tarkovsky-stalker.md",
]

# Total project timing (sum of shot durations)
total_duration_seconds = 30

# Shot list (in narrative order)
[[shots]]
# ... per shot
```

## Per-shot schema

```toml
[[shots]]
id = "shot-1"                           # required; cross-modal join key
order = 1                               # required; sequence in final cut
duration = 5                            # required; seconds (sum to total_duration_seconds)

# Narrative anchor (from narrative_outline.md)
narrative_ref = "act-1.scene-1"
narrative_summary = "苹果在山间露珠中诞生"   # 1-line summary, ≤30 chars

# Cinematic decisions (builder-av authors based on cookbook + reference learning)
shot_type = "close-up"                  # required; CU / MS / WS / OTS / POV / extreme-CU / wide / aerial
camera_motion = "slow zoom-in"          # required; static / pan-L / pan-R / dolly-in / dolly-out / crane-up / crane-down / handheld / steadicam / ...
camera_angle = "low-angle"              # optional; eye-level / high / low / dutch / overhead
lens_feel = "shallow-dof, 50mm"          # optional; helps L3 prompt translation
mood = "宁静神秘"                        # required; ≤8 char tag

# Style anchors (from style_bible)
key_elements = ["苹果", "露珠", "晨雾"]   # required; concrete subjects in the shot
palette_anchor = "deep-red, cool-blue"   # optional; overrides style_bible default
lighting_anchor = "low-key, ambient cool" # optional

# Character anchors (from character_dna)
characters = []                          # ids from character_dna.json; empty if no character

# Cross-modal handoff
input_image = null                       # null for first shot; "shot-X.picked" for subsequent
audio_overlay = "BGM"                    # which audio lane this shot should sync to: "BGM" / "VO-1" / "SFX-1" / null

# Reference inspirations (from reference-learning subagents)
references = ["wong-kar-wai-itmfl.md#scene-3"]   # optional; informs L3 translation

# Notes (free-form, builder-av or user can add)
notes = "the apple should feel ceremonial, almost held"
```

## Field descriptions

### Required fields

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique within project. Cross-modal join key. Format: `shot-N` or `shot-N-a` (alt) |
| `order` | int | Sequence in final cut (1-indexed) |
| `duration` | int (seconds) | Per-shot duration; total must match project total |
| `narrative_ref` | string | Anchor to `narrative_outline.md` section |
| `narrative_summary` | string ≤30 char | Quick label for tournament UI |
| `shot_type` | enum | Standard cinematic vocabulary |
| `camera_motion` | enum | Standard cinematic vocabulary |
| `mood` | string ≤8 char | Cross-references style_bible mood tags |
| `key_elements` | array<string> | Subjects / props / setting elements |

### Optional fields

| Field | Type | Description |
|---|---|---|
| `camera_angle` | enum | Eye-level / high / low / dutch / overhead |
| `lens_feel` | string | DoF / focal length hint for L3 translation |
| `palette_anchor` | string | Per-shot color override of style_bible |
| `lighting_anchor` | string | Per-shot lighting override |
| `characters` | array<string> | character_dna.json ids appearing |
| `input_image` | string \| null | Cross-modal: which prior picked image to use as i2v input |
| `audio_overlay` | string \| null | Which audio lane this shot syncs to |
| `references` | array<string> | reference-learning subagent reports informing this shot |
| `notes` | string | Free-form builder-av or user comments |

## Enums

### shot_type

| Value | Definition |
|---|---|
| `extreme-CU` | Eyes / detail / texture only |
| `close-up` | Face / object filling frame |
| `medium-shot` | Waist-up / mid-distance object |
| `wide-shot` | Full body / setting visible |
| `aerial` | Drone / high overhead |
| `OTS` | Over-the-shoulder |
| `POV` | First-person view |
| `establishing` | Wide context-setting shot |

### camera_motion

| Value | Definition |
|---|---|
| `static` | Camera locked off |
| `pan-L` / `pan-R` | Horizontal rotation, left or right |
| `tilt-up` / `tilt-down` | Vertical rotation |
| `dolly-in` / `dolly-out` | Camera moves toward / away from subject |
| `truck-L` / `truck-R` | Camera slides sideways |
| `crane-up` / `crane-down` | Camera rises / falls |
| `handheld` | Organic shake; verite feel |
| `steadicam` | Smooth follow |
| `slow zoom-in` / `slow zoom-out` | Lens-driven, no camera movement |
| `whip-pan` | Fast pan, motion blur |

These enums map to Seedance 2.0 mode parameters. See
`cartooner-seedance-cookbook` for full mappings.

## Cross-modal consistency rules

1. **shot_id consistency**: A shot's id is fixed. Lanes referencing
   `shot_id="shot-1"` always belong to that shot.
2. **input_image dependency**: If `input_image = "shot-1.picked"`, the
   builder-av video lane for shot-2 cannot start until shot-1's image
   tournament has a winner.
3. **duration sum**: Sum of all `shots[].duration` must equal
   `total_duration_seconds`. Memory verifies this on shot_list deposit.
4. **character continuity**: `characters` field is metadata; memory
   verifies cross-shot character_id references exist in
   character_dna.json. Memory does NOT verify visual character
   consistency (that's user's job at pick time).

## Authoring workflow (builder-av STAGE 1)

```
[memory dispatch builder-av STAGE 1]
"author shot_list per narrative_outline.md@v3 + style_bible.md@v2"

[builder-av main thread]
1. Read narrative_outline.md (text only)
2. Read style_bible.md (text only)
3. Read character_dna.json (text only)
4. Optional: invoke reference-learning subagent(s) for shot grounding
   - "ingest @youtube/wong-kar-wai/itmfl"
   - subagent returns text shot-analysis
5. Decompose narrative into shots:
   - Determine shot count and duration distribution
   - Per-shot: shot_type, camera_motion, mood, key_elements, etc.
6. Author shot_list.toml
7. report_to_memory.py --event shot_list_authored --triggered-by memory --seat builder-av
8. memory verifies: total duration, schema, narrative_ref, character refs
9. memory escalates to user for review
10. user approves → shot_list.toml frozen at v1
    user rejects → builder-av iterates per user feedback (L2b mutation)
```

## Iteration on shot_list (L2 feedback, target=shot_list)

When user gives feedback on shot_list ("shot 5 should be wide instead of
close-up"), `iterate_prompt.py` routes at layer L2 with `--target shot_list`:

```
iterate_prompt.py --project <project-id> \
  --layer L2 \
  --target shot_list \
  --parent-shot shot-5 \
  --feedback "shot-5 change to wide-shot"
```

(L1 / L2 / L3 are the layer enums; the L2a [narrative] vs L2b [shot list]
split documented in `3-layer-prompt-model.md` is captured by `--target`.)

builder-av:
1. Reads current shot_list.toml
2. Mutates shot-5 fields (shot_type → wide-shot; camera_motion may also need adjustment)
3. Authors v2 of shot_list.toml
4. report_to_memory shot_list_revised
5. Memory invalidates any pending image / video lanes referencing shot-5
   (lanes get superseded; their assets become orphan)
6. Memory escalates to user for re-approval
7. On approval, downstream lanes can be re-spawned

L2b mutations are localized: only lanes referencing the changed shot need
re-spawn. Other shots' lanes are unaffected.

## Storage and versioning

shot_list.toml is versioned via git-style snapshots in
`~/.cartooner/projects/<id>/shot_list.history/`:

```
shot_list.history/
├── v1.toml
├── v2.toml
└── v3.toml   <- current symlinked from shot_list.toml
```

Each version is immutable. Lanes reference specific versions
(`shot_list_ref = "shot_list.toml@v3"`) so audit can reconstruct which
shot list version produced which asset.

## Memory's role with shot_list

Memory is the consumer + cross-reference checker. Memory:
- Verifies schema validity on deposit
- Verifies duration sum
- Tracks which assets reference which shot version
- Detects stale references (lane references shot_list@v1 but project is
  on v3)
- Never edits shot_list.toml (only builder-av writes it)
- Never views the resulting images / videos for shot list compliance
  (no-image-policy)
