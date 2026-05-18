# 3-Layer Prompt Model

Creative prompt engineering is split across three layers; each seat owns
exactly one layer. This is the rule that prevents context pollution and
keeps prompt expertise where it belongs.

## The three layers

```
┌────────────────────────────────────────────────────────────────────┐
│ L1 — Creative Intent                                                │
│   "30 秒红苹果广告，国风暗黑情绪，目标抖音 25-35 岁女性"            │
│   Owner: user (Creator) ↔ memory                                    │
│   Files: brief.md, style_bible.md, vision_spec.md                   │
│   Format: free-form natural language                                │
└────────────────────────────────────────────────────────────────────┘
              │
              │ memory dispatches writer to author narrative
              ▼
┌────────────────────────────────────────────────────────────────────┐
│ L2a — Narrative Outline (literary)                                  │
│   "苹果在山间露珠中诞生，月光下凝视..."                              │
│   Owner: writer (Story Specialist)                                  │
│   File: narrative_outline.md                                        │
│   Format: prose / scene breakdown / dialogue / emotional beats      │
└────────────────────────────────────────────────────────────────────┘
              │
              │ memory dispatches builder-av to author shot list
              │ (builder-av may invoke reference-learning subagent for
              │  YouTube reference grounding)
              ▼
┌────────────────────────────────────────────────────────────────────┐
│ L2b — Shot List (cinematic metadata)                                │
│   shot-1: close-up, 5s, slow zoom-in, mood=宁静神秘, ...            │
│   Owner: builder-av (AV Cinematographer)                            │
│   File: shot_list.toml                                              │
│   Format: structured TOML; each shot has id for cross-modal join    │
└────────────────────────────────────────────────────────────────────┘
              │
              │ spawn_lane dispatches builder-image (per shot)
              │ spawn_lane dispatches builder-av (per shot, after image picked)
              ▼
┌────────────────────────────────────────────────────────────────────┐
│ L3 — Model-Specific Prompt                                          │
│   Image: "@nano-banana --close-up --water-drop --shallow-dof ..."   │
│   Video: "@seedance --mode=i2v --duration=5s --motion=slow-zoom..." │
│   Audio: "@minimax --music --genre=ambient --mood=mystic ..."       │
│   Owners:                                                            │
│     - builder-image (image prompts: nb2 / nbp / gpt-image-2)        │
│     - builder-av (video / audio prompts)                            │
│   Storage: lane.toml#prompt (per candidate)                         │
└────────────────────────────────────────────────────────────────────┘
              │
              │ cartooner-image / -video / -audio invoked
              ▼
            asset
```

## Why L2 is split into 2a (narrative) and 2b (shot list)

Creative work has two distinct cognitive tasks at the L2 layer:

| L2a — Narrative | L2b — Shot list |
|---|---|
| What happens in the story | How to film it |
| Emotional / dialogue / character arc | shot_type / duration / camera motion |
| Owned by literary specialist | Owned by cinematographer |
| Free-form prose | Structured metadata |

A traditional film production has both screenwriter (L2a) and director +
storyboard artist (L2b) splitting these concerns. AIGC keeps the same
split because the cognitive demands are different:
- L2a needs strong literary skill, language fluency, character empathy
- L2b needs cinematic vocabulary (Seedance modes, camera language,
  reference learning from master cinematographers' work)

Asking `writer` (literary specialist) to also do L2b would overload it
with a domain (videography) outside its expertise. Asking `builder-av` to
also do L2a would burden it with literary work that should serve the
narrative arc, not the visual mode.

## Why builder-av owns L2b (not builder-image)

`builder-av` handles motion / time / sound — domains where shot decisions
have most consequence. A still image's "shot type" matters less than a
video's because:
- Duration belongs to video, not still
- Camera motion (pan / dolly / crane) belongs to video
- Cross-shot rhythm is a video editing concern
- Seedance 2.0's 13 modes encode shot grammar

`cartooner-seedance-cookbook` (50 production recipes + 47 technique atoms
across camera / lighting / motion / sound / composition) is loaded only on
`builder-av`. This is where shot vocabulary lives.

`builder-image` consumes the shot_list (reads shot-1 → outputs key frame
matching that shot's type / mood / composition) but does not author it.

## Why builder-av needs Gemini for L2b

Master cinematic shot vocabulary is largely **non-textual** — it lives in
how Wong Kar-wai composes, how Tarkovsky paces, how Edgar Wright cuts.
Text descriptions of these styles are pale shadows of the actual works.

Gemini is the only LLM provider with **YouTube video ingestion** as a
native capability. `builder-av` invokes a **reference-learning subagent**
that:
1. Receives YouTube URL (e.g., a Wong Kar-wai music video reference)
2. Ingests the video in isolated subagent context
3. Outputs a text shot-analysis report ("50mm + slow dolly + low-key
   lighting + 暧昧色温 + ~8s shot rhythm + 跳切 vs slow-cut alternation")
4. Returns text only; subagent context discarded

`builder-av`'s main thread incorporates the text reference into its
shot_list authoring, never seeing the video itself. The reference is now
distilled, audit-able, and re-usable across shots.

## Routing user feedback (`iterate_prompt.py`)

User feedback determines which layer is mutated. `iterate_prompt.py`
accepts `--layer L1|L2|L3`; the L2a (narrative) vs L2b (shot list) split
is captured by `--target narrative_outline` vs `--target shot_list`:

| User feedback | --layer | --target | Target seat | Cache impact |
|---|---|---|---|---|
| "Wrong target audience" | L1 | brief / vision_spec | memory edits, may re-collaborate with user | Full re-plan |
| "Wrong concept entirely" | L1 | style_bible | memory + user | Style bible v2 |
| "Shot 3 dialogue wrong" | L2 | narrative_outline | writer revises narrative_outline | writer context only |
| "Shot 5 should be wide instead of close-up" | L2 | shot_list | builder-av revises shot_list | builder-av context only |
| "All 4 candidates too bright" | L3 | lane | builder-image (root-cause subagent → adjust prompt → re-spawn) | builder-image lane only |
| "BGM too fast" | L3 | lane | builder-av (root-cause subagent → adjust prompt → re-spawn) | builder-av lane only |
| "Want longer / shorter shot" | L2 | shot_list | builder-av | builder-av context |

Memory classifies feedback heuristically. Two safeguards:

1. **Producer override**: user may explicitly say "this is L2b — change
   the shot to wide" — memory routes accordingly without classifying.
2. **Hop-up rule**: if a feedback dispatched to L3 produces no
   improvement after `iterate_max_attempts`, memory escalates to L2 (or
   L1) automatically. The wrong layer eventually surfaces as the wrong
   intervention.

## Forbidden cross-layer actions

| Layer | Forbidden | Reason |
|---|---|---|
| L1 (memory) | Writing model-specific prompts | Pollutes memory context; bypasses prompt-engineer expertise |
| L1 (memory) | Drafting full narrative or shot lists | Pollutes memory context |
| L2a (writer) | Loading `cartooner-prompt` references | Tempts writer to write L3 syntax it doesn't maintain |
| L2a (writer) | Camera / shot decisions | That's L2b (builder-av) |
| L2a (writer) | Generating any asset | Wrong tool; writer is text-only |
| L2b (builder-av) | Drafting narrative dialogue | That's L2a (writer) |
| L2b (builder-av) | Generating without reading shot_list | Shot list is the input contract |
| L3 (builder-image) | Editing `narrative_outline.md` or `shot_list.toml` | These are L2 artifacts; consume only |
| L3 (builder-image) | Auto-picking own candidates | Pick belongs to user (or to memory only with model-metadata-rank) |
| L3 (builder-av) | Same as L3 (builder-image) | Same constraints |

A seat that violates these rules is a protocol violation. `patrol` may
detect violations through transcript signatures (e.g., "writer never
invokes cartooner-image") and alert memory.

## Example walk-through (full project)

```
[Producer / user → memory]
"我要 30 秒红苹果广告，国风暗黑"

[L1: memory ↔ user]
brief.md:
  goal: 30s ad for red apple, douyin platform
  audience: women 25-35
style_bible.md:
  tone: 国风暗黑
  palette: deep red, ink black, cool blue accents
  mood: 静谧 / 神秘 / 仪式感
vision_spec.md (auto mode):
  pick_strategy: escalate-always
  escalate_on: [phase_transition, all_candidates_rejected, sla_breach, ...]

[memory dispatches writer]
"draft narrative_outline.md per style_bible v1"

[L2a: writer drafts narrative_outline.md]
- 第一幕：苹果在山间露珠中诞生，朝阳未起
- 第二幕：月光下，山顶古亭，苹果被托起
- 第三幕：露珠从苹果滑落，象征仪式完成
- (no shot decisions, just narrative)

[user reviews narrative, approves]

[memory dispatches builder-av to author shot_list]
"based on narrative_outline + style_bible, write shot_list.toml"

[builder-av may invoke reference-learning subagent]
- "ingest @youtube/wong-kar-wai/in-the-mood-for-love for shot reference"
- subagent: vision input → text shot-analysis report
- main thread: text report integrated into shot_list authoring

[L2b: builder-av drafts shot_list.toml]
[[shots]]
id = "shot-1"
duration = 5
shot_type = "close-up"
camera_motion = "slow zoom-in"
mood = "宁静神秘"
key_elements = ["苹果", "露珠", "晨雾"]
input_image = null   # first shot, no input

[[shots]]
id = "shot-2"
duration = 8
shot_type = "wide-shot"
camera_motion = "static, low angle"
mood = "孤寂仪式感"
key_elements = ["古亭", "月光", "苹果"]
input_image = "shot-1.picked"

...

[user reviews shot_list, approves]

[memory spawns image lanes]
spawn_lane(seat=builder-image, count=4, shot_id="shot-1")
spawn_lane(seat=builder-image, count=4, shot_id="shot-2")

[L3: builder-image translates per shot]
shot-1 → @nano-banana --close-up --water-drop --shallow-dof --tone-cool
shot-2 → @gpt-image-2 --wide-shot --moonlit --traditional-pavilion ...
(builder-image picks model per shot semantics)

[builder-image generates 8 candidates total, deposits all]

[memory runs tournaments]
tournament-shot-1 (4 candidates) → user picks #2
tournament-shot-2 (4 candidates) → user picks #5

[memory passes picks to builder-av video phase]
spawn_lane(seat=builder-av, count=2, shot_id="shot-1",
           input_image=img-002)

[L3: builder-av translates per shot to Seedance]
shot-1 video → @seedance --mode=i2v --duration=5s --motion=slow-zoom-in --ref=img-002
shot-2 video → @seedance --mode=i2v --duration=8s --motion=static --ref=img-005

[user picks final video for each shot]

[memory dispatches builder-av for audio]
spawn_lane(seat=builder-av, count=3, kind=music,
           prompt="国风暗黑 BGM, 30s, dynamic")
[user picks BGM]

[memory integrates final mp4]
```

Notice how:
- L1 never touches model-specific syntax
- L2a never touches model choice (nb2 vs gpt-image-2 vs Seedance)
- L2b never touches dialogue / character emotion (those are narrative)
- L3 never touches narrative judgment

Each seat does what it knows. The 3-layer split is what makes this
specialization sustainable.
