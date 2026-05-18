# Subagent Protocol

The **only sanctioned mechanism** for any seat (other than `user`) to
view asset content or external reference media is via **isolated
subagents**.

This document specifies the two subagent types and their contracts.

## Why subagents

Per [no-image-policy](no-image-policy.md), main-thread LLM context for
any seat must remain free of asset content (image / video / audio bytes).
But some operations genuinely need vision input:

- **Root cause analysis**: when user feedback says "all 4 are wrong",
  builder-image must look at the candidates to identify what's wrong.
- **Reference learning**: when memory or user wants to ground shot
  decisions in master cinematic works, builder-av needs to ingest those
  works.

Subagents solve this with **context isolation**: a subagent runs in a
separate LLM call with its own context, ingests vision input,
synthesizes a text-only report, returns the text to the main thread,
and discards its own context.

## Subagent boundary contract

Every subagent must:

1. **Run as a separate LLM call** — not inline in main thread
2. **Receive only text inputs from main thread** (paths, URLs, parameters)
3. **Return only text output to main thread** (analysis report,
   structured findings)
4. **Discard its context on return** — main thread never sees subagent's
   working tokens
5. **Not invoke nested subagents** (no recursion; flat boundary)
6. **Be auditable** — subagent inputs and outputs logged to
   `~/.cartooner/projects/<id>/references_learned/<subagent-id>.md`

The subagent runtime requirement is supported by Claude API tool-use
sub-calls and Gemini API equivalent capabilities. If the runtime does not
support context isolation, the seat must escalate to user instead of
attempting in-main-thread workarounds.

## Subagent types

### 1. Root-cause subagent

**When triggered**: User feedback that requires inspecting generated
assets to find the cause.

**Caller**: `builder-image` or `builder-av`

**Inputs**:
- List of candidate asset paths (≤8 typically)
- User's text feedback verbatim ("too bright", "wrong angle", etc.)

**Process** (subagent context):
1. Load each candidate as vision input
2. Compare against user's complaint
3. Identify per-candidate root cause
4. (Do not propose fix — that's the main thread's job)

**Output**: Text root-cause report

```markdown
# Root cause analysis for tournament-shot-1-r1
User feedback: "all 4 are too bright"

## Per-candidate findings
- img-042-a: Highlight blowout in top-right (overexposed sky region)
- img-042-b: Overall ambient too high; entire frame ~+2 stops
- img-042-c: Specular highlights on apple too strong; surface treatment
- img-042-d: Within acceptable range; could be retained

## Common pattern
3 of 4 candidates show ambient lighting too strong; suggests model is
defaulting to "well-lit" interpretation of "natural lighting".

## Suggested L3 adjustment direction (not prescriptive)
Add explicit "low-key", "ambient -2 stops", "rim-light only" tokens.
```

**Main thread action**: Reads text report, decides L3 prompt adjustment,
spawns iteration lane.

**Storage**: `references_learned/root-cause-<round-id>.md`

### 2. Reference-learning subagent

**When triggered**: Memory or user explicitly provides a reference URL
(typically YouTube video for cinematic learning).

**Caller**: `builder-av` (primary use case); `builder-image` may use for
photographic reference (less common, since image generation has fewer
reference-learning needs).

**Inputs**:
- Reference URL (YouTube / external video / image URL)
- Learning focus (e.g., "shot rhythm and camera motion", "color grading",
  "composition language")

**Process** (subagent context):
1. Ingest the referenced media (Gemini's YouTube ingestion or direct
   media analysis)
2. Extract the requested aspects (rhythm / motion / color / composition)
3. Synthesize text shot-analysis report

**Output**: Text reference report

```markdown
# Reference: Wong Kar-wai — In the Mood for Love (excerpt 03:14-04:32)
Focus: shot rhythm and camera motion

## Identified shot grammar
- Shot rhythm: 6-8s avg; deliberate, contemplative
- Camera motion: 80% static; 15% slow tracking; 5% rack focus
- Lensing: long lens (>85mm) for compression; shallow DoF
- Color: warm-cool split (yellow interiors vs blue exteriors); high
  saturation but desaturated highlights

## Repeatable techniques
- "Negative space framing": subject offset ~1/3 from frame edge,
  large architectural element framing
- "Slow motion via slow shutter, not interpolation": creates dreamy
  texture rather than smooth-mo
- "Cigarette smoke as tension marker": diegetic motion in otherwise
  static frame

## Applicability to current project (style_bible:国风暗黑)
- Slow rhythm aligns with 静谧/仪式感 mood
- Long lens compression supports "intimate close-ups despite formal
  composition"
- Warm-cool split could map to: warm internal (apple) vs cool external
  (mountain mist)
```

**Main thread action**: Reads text report, integrates findings into
shot_list authoring decisions; cites the reference report id in
shot_list.toml's `references` field.

**Storage**: `references_learned/<provider>-<title-slug>.md`

## Concurrency cap (audit finding #12, 2026-05-11)

`spawn_subagent.py --action spawn` enforces a per-caller cap on
in-flight (state=`spawned`) subagents via `--max-concurrent` (default 4).
Once exceeded, spawn fails closed until the caller completes / fails one
of its prior subagents.

| Caller seat | Tool | Recommended `--max-concurrent` |
|---|---|---|
| `builder-image` | Codex CLI | **4** (default; Codex tolerates parallel function calls) |
| `builder-av` | Gemini CLI | **1** (strict serial; see below) |

**Why builder-av must serialize**: Gemini's function-calling API rejects
follow-on conversation turns when a prior turn has parallel tool calls
with unmatched response parts. Symptom (observed in clawseat-storyboard-test
2026-05-11): main thread crashes with
`status: INVALID_ARGUMENT — number of function response parts is equal
to the number of function call parts of the function call turn`. Calling
`spawn_subagent --action spawn` three times in parallel within one Gemini
turn is the reproducer.

**Workaround pattern for builder-av**:

```bash
# spawn-1
spawn_subagent.py --action spawn --max-concurrent 1 --seat builder-av \
    --subagent-type reference_learning --inputs '{"reference_url": "..."}'
# (run subagent's vision call in a separate Gemini sub-turn,
#  write report to references_learned/<id>.md)
spawn_subagent.py --action complete --subagent-id <id> --report-path ...

# spawn-2 (only after #1 completes)
spawn_subagent.py --action spawn --max-concurrent 1 --seat builder-av ...
```

If builder-av needs to compare N candidates, spawn ONE subagent with
all N candidate paths in the inputs JSON — let the subagent do the
comparison in its single isolated context. Spawning N parallel subagents
is both a Gemini-API hazard and a context-cost waste.

## Why builder-av uses Gemini for this

Reference-learning subagents need video ingestion. Among LLM providers:

| Provider | Video ingestion |
|---|---|
| Claude (Anthropic) | Image only; no video |
| GPT-4 / Codex (OpenAI) | Image only; no video |
| **Gemini (Google)** | **Video ingestion native, including YouTube URLs** |

Gemini is the only LLM with this capability at the time of writing.
`builder-av` is therefore configured with `tool=gemini, provider=google`
specifically for this subagent path.

If Anthropic or OpenAI add video ingestion in the future, builder-av's
tool can be reconfigured. The protocol does not bind to a specific
provider; it binds to **the capability**.

## Forbidden subagent patterns

| Pattern | Why forbidden |
|---|---|
| Subagent invokes another subagent | Recursion creates ambiguous context boundary; flat hierarchy only |
| Subagent passes vision content back to main thread | Defeats the entire purpose; main thread must remain image-free |
| Subagent runs in main-thread context (e.g., Claude tool-use that shares context) | Not isolated; pollutes main thread |
| Reference-learning subagent for non-creative purposes (e.g., "look at this contract PDF") | Out of scope; reference-learning is for creative shot vocabulary |
| Root-cause subagent without prior user feedback | This is "self-eval" in disguise; no-image-policy violation |
| Subagent that writes/modifies assets | Subagents are read-only analyzers; only main thread can deposit |

## When NOT to use a subagent

If the question can be answered from text-only signals, **do not** spawn
a subagent. Examples:

- "Did the lane succeed?" → check `api_status` and file metadata, not
  vision
- "Is character_id consistent?" → check metadata field, not visual
  identity
- "What model produced img-042-a?" → check generation_log, not the
  image
- "Is this the right shot in sequence?" → check shot_list ordering, not
  visual content

Subagents are expensive (LLM call + vision tokens). Only use when
text-only is genuinely insufficient.

## Audit trail

All subagent calls are logged:

```jsonl
{"ts": "...", "event": "subagent_spawned", "type": "reference_learning",
 "caller": "builder-av", "inputs": {"url": "...", "focus": "..."},
 "subagent_id": "ref-001"}
{"ts": "...", "event": "subagent_completed", "subagent_id": "ref-001",
 "output_file": "references_learned/wong-kar-wai-itmfl.md",
 "output_size_chars": 1840, "duration_seconds": 12,
 "tokens_input_vision": 8400, "tokens_output_text": 920}
```

Memory tracks subagent usage in `generation_log.jsonl` so:
- Audit can reconstruct what informed each shot decision
- Budget tracking includes subagent token costs
- Patrol can detect anomalies (e.g., builder-image spawning many
  root-cause subagents per round → upstream prompt quality issue)
