# No-Image Policy (Protocol-Level Hard Rule)

**This is a hard rule. Violating it breaks the protocol.**

## The rule

| Role | Permitted to view image / video / audio content? |
|---|---|
| `user` | ✅ Unlimited (real human, no context limit) |
| `builder-image` / `builder-av` | ✅ **Only inside a root-cause subagent** triggered by user feedback |
| `memory` | ❌ **Never. Period.** |
| `writer` | ❌ Never |
| `patrol` | ❌ Never (file metadata only — size / exists / hash) |

`builder-image` and `builder-av` **do not** view their own output after
generation. They are prompt-translation + API-dispatch + asset-deposit
machines, not image / video / audio reviewers.

## Why this rule exists

LLM agents have finite context windows and cache mechanisms. Image / video /
audio inputs are **expensive in tokens**:

| Asset type | Approx tokens (vision input) |
|---|---|
| One mid-resolution image | ~1.5K tokens |
| One 5s video (sampled keyframes) | ~3-5K tokens |
| 4-candidate tournament | ~6K tokens |
| 30-second project, 5 phases × 3 rounds × 4 candidates | **~90-180K tokens** |
| Same project with iteration | **~150-400K tokens** |

A `memory` seat that views every candidate would accumulate hundreds of K
tokens of asset content. Effects:

1. **Baseline explosion** — memory's working baseline grows from ~10K to
   >100K tokens.
2. **Cache thrash** — every new image inserted mid-context invalidates the
   prompt cache for everything before it.
3. **Cross-project context pollution** — long-running projects (hours / days)
   become unworkable because memory drowns in its own historical assets.
4. **Cost** — token consumption scales linearly with project length × 100×
   compared to a text-only memory.

`builder-image` self-eval (a previous design we explicitly rejected) had
the same problem at the lane scale: every lane spawned would accrue ~6K
tokens of vision context just to "self-evaluate", with no real value
because:

- The model that generated the image cannot meaningfully critique its own
  output (confirmation bias).
- Self-eval text correlates poorly with how a human reviewer judges the
  same image.
- The Producer (user) is the actual aesthetic judge — adding an LLM
  pseudo-judge upstream is theater, not value.

## What replaces "looking at the image"?

For everything except real picks (which `user` does), use **text-only signals**:

| Decision | Signal source | NOT |
|---|---|---|
| Did the lane succeed? | `api_status == 200` + file exists + size > 0 | LLM looking at image |
| Is style compliant? | **No automated check.** User picks. | LLM judging style_bible |
| Is character continuity preserved? | Metadata diff: asset's `character_id` field vs character_dna | LLM comparing images |
| Auto-pick a winner? | Model-provided `aesthetic_score` (if available); else **escalate user** | LLM ranking candidates |
| Iterate prompt direction? | User's text feedback ("too bright"); routed to L1/L2/L3 | LLM inferring "what's wrong" |

If a decision genuinely requires looking at the image, the answer is
**escalate to user**. There is no in-LLM substitute.

## The one exception: root-cause subagent

When the Producer says "all 4 are wrong, too bright" and the cause is not
inferrable from metadata, `builder-image` may spawn a **root-cause
subagent** — a single, isolated LLM call that:

1. Receives the candidate paths
2. Loads them as vision input
3. Outputs a text root-cause report ("img-042-a high-light blowout
   top-right; -b overall too bright; -c ambient too strong; -d ok")
4. Returns the text report to `builder-image`'s main thread
5. **Subagent context is discarded immediately**

The main `builder-image` thread receives only the text report, never the
images. Its long context remains image-free.

```
builder-image main thread
    │
    │ user feedback: "all too bright"
    │
    ├──── spawn subagent ─────────────────────────────┐
    │                                                  │
    │     [subagent context, isolated]                 │
    │     - vision input: 4 candidates                 │
    │     - analysis                                   │
    │     - output: text root-cause report             │
    │     - context discarded on return                │
    │                                                  │
    ◀─── text report only ─────────────────────────────┘
    │
    │ adjust L3 prompt based on text report
    │ spawn_lane re-spawn with adjusted prompt
    │
    └──▶ continue
```

The subagent is the **only** sanctioned image-viewing path for any seat
other than `user`. Implementation note: this requires the LLM runtime to
support nested LLM calls with context isolation (Claude API's tool-use
sub-call, or similar). If the runtime does not support this, the only
correct fallback is to escalate to user — never to view images in the
main thread.

## Forbidden patterns

These design patterns are explicitly forbidden by this policy:

| Forbidden pattern | Why |
|---|---|
| `builder-image` self-eval after generation | Wastes tokens, no value, confirmation bias |
| `memory` running `LLM_judge(candidate, style_bible)` | memory must never see images |
| `memory` reading deposited assets to verify deposit succeeded | Use file metadata + api_status |
| `auto_pick` strategy = "llm-judge" | This requires viewing images; remove this strategy |
| `style_drift` detection by LLM comparison | Use metadata diff or escalate user |
| `patrol` viewing assets to verify content | Patrol checks file integrity (size/hash/exists), not content |
| Embedding image bytes in `generation_log.jsonl` | Log carries paths, never bytes |
| Embedding image bytes in `report_to_memory.py` payload | Reports carry text + metadata, never bytes |
| `writer` viewing reference images while drafting `script.md` | Writer is text-only |
| Showing memory a thumbnail "just to update its understanding" | Even thumbnails are tokens; memory does not need to know what assets look like |

## How compliance is enforced

The no-image-policy is enforced through three independent layers, each
catching a different failure mode:

1. **Prose** — every seat's role contract (in `AGENTS.md` / `CLAUDE.md`)
   states the rule explicitly, so the LLM self-restrains.
2. **Gate** — `seat_gate.{mjs,py}` at every cartooner-* skill CLI entry
   blocks unauthorized seats from invoking image / video / audio
   generation skills (see [`seat-authorization-enforcement.md`](seat-authorization-enforcement.md)).
3. **Audit** — `patrol_pipeline_sla.py --check authorization` scans
   `generation_log.jsonl` for events whose actor is outside the authorized
   list (e.g., `memory` calling `cartooner-audio.generate_song.mjs`).
   Append-only log + actor allowlist makes any violation forensic.

A patrol-detected violation triggers `seat_authorization_violation`,
which (in auto mode) flips memory back to manual and escalates to the
user. The protocol's value proposition (long-running, cache-friendly,
scalable creative projects) collapses if this policy is not enforced.

Patrol does not currently inspect session transcripts for vision-input
markers — that capability lives outside the protocol scripts. The gate
+ audit layers are the authoritative enforcement surfaces.

## What the user explicitly authorized

This policy was explicitly authorized by the Producer in the protocol
design phase, with the rationale: **"AIGC 工作流的核心是 user 看图 + 模型出图。
任何 LLM seat 看图都是浪费 token 和上下文。"**

That is the protocol's bedrock. All other design decisions in
cartooner-harness derive from this.
