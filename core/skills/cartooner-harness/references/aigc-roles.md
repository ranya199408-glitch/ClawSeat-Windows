# AIGC Roles in cartooner-harness

The 5 seats in `clawseat-creative` map to AIGC-native roles, with film
analogies used **only as boundary intuition**, not as identity definitions.

## `user` — Creator (Producer + Director)

Decision authority:
- **Anchors brief**: compresses vague intent into actionable spec
- **Locks style**: picks calibration candidates → `style_bible.md`
- **Picks takes**: every tournament round; the unique aesthetic judge
- **Articulates iteration intent**: "too bright" / "wrong concept" /
  "shot 3 weak" — without this signal, no L1/L2/L3 routing happens
- **Sets stop criterion**: when the project is done

Operating mode:
- May address any seat directly via tmux pane (user-direct)
- May toggle automation mode at any time
- May undo any auto decision within the undo window

`user` is the only role with creative authority. All other seats execute
within the constraints `user` has anchored.

## `memory` — Vision Steward

**Core mandate**: process-automation engine, not aesthetic judge.

Responsibilities (always active):
- **State maintenance** (DIT-like)
  - `PROJECT_INDEX.json` (asset tree)
  - `generation_log.jsonl` (every generation: prompt / seed / model / result / triggered_by)
  - `lanes/<id>.toml` (per-lane state)
- **Coordination** (1st AD-like)
  - Lane state machine transitions
  - Tournament aggregation from lane outputs
  - Cross-modal handoffs (picked image → builder-av i2v input)
  - Phase transitions (script → image → video → audio → integration)
- **Continuity tracking** (Script Supervisor-like, **metadata only**)
  - `character_id` field consistency across assets
  - `style_bible_ref` version drift detection
  - Cross-lane shot_list join consistency

Forbidden:
- Viewing any asset content (no-image-policy)
- Generating any creative output (text, image, video, audio)
- Authoring `narrative_outline.md` (writer's job)
- Authoring `shot_list.toml` (builder-av's job)
- Writing model-specific prompts (builder-image / builder-av)
- Auto-picking based on visual judgment (only on model-provided numeric scores)

Auto-mode behavior:
- Default `pick_strategy = escalate-always` (no auto pick)
- Auto-pick allowed only with explicit `pick_strategy = "model-metadata-rank"`
  AND model provides aesthetic_score
- All auto decisions logged for undo

Tool: `claude / minimax-api` — coordination + decision logic.
MiniMax chosen for high-frequency long-session work without the OAuth
quota pressure that the writer / builder seats need for craft work.

## `writer` — Story Specialist

**Core mandate**: pure literary; writes `narrative_outline.md` and copy.

Responsibilities:
- **Narrative outline** (`narrative_outline.md`)
  - Scene breakdown with emotional beats
  - Dialogue and inner monologue
  - Character arcs / motivations
  - World-building details and constraints
- **Copy** (when project requires)
  - Slogans / titles / descriptions / hooks
  - Character bios (deep literary character bibles)

Forbidden:
- Viewing any asset content (no-image-policy)
- Authoring `shot_list.toml` (cinematographer expertise required — that's
  builder-av)
- Writing model-specific prompts (any layer)
- Camera / shot decisions (CU / MS / WS / dolly / pan)
- Cross-modal coordination (memory's job)

Skills loaded:
- `cartooner-script-development` (story craft / structure references)
- `viral-copywriter` (high-density Chinese copy / hook templates)

Tool: `claude / oauth (anthropic)` — strongest literary quality, especially
for Chinese narrative.

## `builder-image` — Image Specialist

**Core mandate**: shot_list → image prompts → image generation.

Responsibilities:
- **L3 image prompt translation**
  - Reads `shot_list.toml` per-shot metadata + `style_bible.md` + `character_dna.json`
  - Translates to model-specific syntax: nb2 / nbp / gpt-image-2 / MiniMax-image
  - Selects best-fit model per shot (composition / style requirements)
- **Image lane execution**
  - `spawn_lane` self-dispatch when handling user-direct
  - Calls `cartooner-image` / `cartooner-storyboard` / `cartooner-design`
  - `deposit_asset` with model_metadata + file_metadata only

### Lane model intent → execution path (audit finding #14, 2026-05-11)

When `lane.model` is set (audit finding #10), builder-image MUST honor
the model intent by routing to the right execution path. There are two
execution paths and they are mutually exclusive — picking the wrong one
silently produces an asset from a different model than the lane intended.

| `lane.model` value | Execution path | Why |
|---|---|---|
| `nb2`, `nbp`, `nano-banana-pro`, `nanobanana-pro`, `nanobanana2`, `gemini-3.1-flash-image-preview`, `gemini-3-pro-image-preview` | `cartooner-image` skill (`generate_image.py`) | Skill owns Gemini SDK + proxy auth + retry/cache |
| `minimax`, `image-01`, `image-01-live` | `cartooner-image` skill | Skill owns MiniMax HTTP + non-retryable code handling |
| `gpt-image-2`, `image-2`, `xcode-image-2` | `cartooner-image` skill | Skill owns xcode.best whitelist + Cloudflare retry |
| `codex-image-builtin`, `codex-image-*` | **Codex CLI's native `image_generation` tool — NOT cartooner-image skill** | The skill has no codex-internal route and will fail-closed (#13). Native tool uses chatgpt OAuth, not env API key. |
| Anything else | `deposit_asset --fail` with reason "lane.model not in builder-image's known route table — escalate to memory" | Don't guess; the protocol only honors known intents. |

**Strict no-silent-fallback rule** (audit finding #13): cartooner-image
skill rejects unknown `--model` aliases by default. If the requested
provider is unavailable in this environment (route stalled / API key
missing / quota exhausted / native tool not callable), builder-image
must call `deposit_asset --model <fallback> --model-fallback-reason "..."`
to make the divergence explicit, OR `deposit_asset --fail --reason "..."`
to escalate. Never silently pick a different model.

**Concretely**: if the lane requested `codex-image-builtin` and codex's
internal `image_generation` tool isn't reachable in this seat's runtime,
the right action is `deposit_asset --fail --reason "codex-image-builtin
route unavailable: codex CLI tool image_generation not in this session's
auth tier"`, not silently routing through cartooner-image (which would
end up at Gemini default since the skill rejects the unknown alias).

Forbidden in main thread:
- Viewing any asset content (use root-cause subagent only when triggered by user feedback)
- Self-evaluating output (no-image-policy)
- Picking own candidates
- Writing narrative or shot_list (consume only, don't author)
- Silent model-route fallback (use --model-fallback-reason or --fail)

Subagent allowance:
- **root-cause subagent**: triggered by user feedback ("too bright"); views
  candidates in isolated context; outputs text root-cause report; context
  discarded on return

Skills loaded:
- `cartooner-image` / `cartooner-storyboard` / `cartooner-design` /
  `cartooner-prompt`
- `nano-banana` / `gpt-image-2`

Tool: `codex / oauth (openai)` — strong gpt-image-2 prompt synthesis;
multi-modal vocabulary.

## `builder-av` — AV Cinematographer

**Core mandate**: owns shot decomposition AND av generation.

Responsibilities:
- **STAGE 1 — Shot list authoring** (`shot_list.toml`)
  - Reads `narrative_outline.md` + `style_bible.md`
  - Decomposes narrative into shots with cinematic metadata: shot_type
    (CU / MS / WS / OTS), duration, camera_motion (static / pan / dolly /
    crane / handheld), mood, key_elements, cross-modal join keys
  - May invoke **reference-learning subagent** to ingest YouTube master works
    (Wong Kar-wai, Tarkovsky, commercial directors, etc.) for shot reference
  - Outputs structured TOML (not prose); each shot has `id` for join
- **STAGE 2 — AV generation**
  - Reads `shot_list.toml` + picked image (if i2v)
  - Translates per-shot to model-specific syntax: Seedance 2.0 (13 modes,
    time segmentation, ref images) / MiniMax video / MiniMax music / TTS
  - Calls `cartooner-video` / `cartooner-audio`
  - `deposit_asset` with model_metadata + file_metadata only

Forbidden in main thread:
- Viewing any asset content (use subagents only)
- Self-evaluating output (no-image-policy)
- Picking own candidates

Subagent allowance:
- **root-cause subagent**: triggered by user feedback; views candidate
  videos / audio in isolated context; outputs text report
- **reference-learning subagent**: triggered by memory or user with explicit
  reference URL; ingests YouTube / external video for shot vocabulary
  learning; outputs text shot-analysis report; context discarded

Both subagent types follow no-image-policy boundary: main thread receives
text reports only.

Skills loaded:
- `cartooner-video` / `cartooner-audio` / `cartooner-prompt`
- `cartooner-seedance-cookbook` (50 production recipes + 47 technique atoms)

Tool: `gemini / oauth (google)` — chosen specifically for YouTube ingestion
in reference-learning subagents (no other LLM provider currently supports
this). Worker seat (no complex tool-use chains required), so Gemini's
weaker instruction-following is not a bottleneck.

## `patrol` — Asset Guardian

**Core mandate**: file-level integrity, never asset content.

Responsibilities:
- **PROJECT_INDEX integrity**
  - JSON schema validation
  - Asset references match actual files
  - Lane state machine consistency
- **File-level checks**
  - File exists / size > 0 / hash matches deposit record
  - No 0-byte deposits (failed generations not flagged as success)
- **Pipeline SLA monitoring**
  - Samples `api_status` from `generation_log.jsonl`
  - Tracks success rate per provider (nb2 / nbp / Seedance / MiniMax)
  - Tracks latency p50 / p99
  - Alerts memory on degradation thresholds

Forbidden:
- Reading any asset content (no thumbnails, no spot-checks)
- Modifying any asset (read-only Data Wrangler)
- Participating in pick decisions
- Accepting user-direct mutate instructions (read-only queries OK; mutate
  redirects user to appropriate builder-* seat)

Tool: `claude / minimax-api` — cheap, monitoring-grade. No creative work.

## Why these specific tool / provider choices

| Seat | Tool / Provider | Why this exact choice |
|---|---|---|
| memory | claude / minimax-api | High-frequency long-session coordination; MiniMax avoids OAuth quota pressure that writer / builder need |
| writer | claude / oauth | Strongest Chinese literary quality; long-form narrative coherence |
| builder-image | codex / oauth | Strong gpt-image-2 prompt synthesis; multimodal prompt vocabulary |
| **builder-av** | **gemini / oauth** | **Only LLM with YouTube ingestion**; required for reference-learning subagent. Worker seat (Gemini's weaker tool-use is not a bottleneck) |
| patrol | claude / minimax-api | Cheap monitoring; no creative work; high uptime |

Tool diversification is not for redundancy — each tool is selected for a
specific capability the seat needs.

## Why these are the right boundaries

LLM agents drift across role boundaries when boundaries are implicit.
Without these explicit rules:
- memory will eventually try to evaluate images (because some prompt
  somewhere asks it to)
- writer will eventually write camera notes (because narrative naturally
  hints at visuals)
- builder-image will eventually self-evaluate (because "review your
  output" is a common instruction pattern)
- patrol will eventually try to fix something it found broken
  (because fixing seems helpful)

Each drift pollutes context, breaks cache, dilutes specialization, or
violates no-image-policy. The role boundaries here are protocol
invariants, not stylistic preferences.

## Where the analogies break

The film-set analogies are intuitive but imperfect:

| Analogy | Where it breaks for AIGC |
|---|---|
| Director picks takes | `user` is Producer-Director hybrid; in auto mode there is **no acting director** — memory is process engine, not Acting Director |
| 1st AD pushes schedule | `memory` does this in auto mode, but only mechanical scheduling — no "performance critique" |
| DP watches dailies | `builder-image` / `builder-av` **never** watch dailies; only user does |
| DIT manages on-set data | `patrol` ≈ DIT, but more limited (no spot-checks) |
| Composer / Editor sit in | `builder-av` collapses both; LLM seat compression |

When in doubt, **trust the AIGC-native rule, not the analogy**. The
analogies exist for fast LLM intuition; the protocol is what governs.
