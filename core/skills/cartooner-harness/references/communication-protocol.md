# Communication Protocol — cartooner-harness

This reference defines how seats in a `clawseat-creative` project send
operational messages to each other. It is the **wakeup-and-state** layer
that complements the **lane / deposit / pick / iterate** state primitives
documented in `lane-model.md` and `tournament-protocol.md`.

Engineering chains use the equivalent `core/skills/gstack-harness/references/communication-protocol.md`
(8 intents, push-primary, durable-truth + wakeup-signal). cartooner-harness
keeps the same architecture but with a creative-flavored intent vocabulary.

## 1. Communication Principles

- **Topology**: hub-and-spoke through `memory`. Cross-seat lateral dispatch
  (e.g., writer → builder-av direct) is **forbidden**. memory is the only
  dispatcher; every `lane` and `brief` originates from memory or from a
  user-direct that has been reported to memory first.
- **Wakeup signal vs durable truth**: every dispatch writes a durable file
  (lane TOML / brief TOML); the wakeup over tmux is just the signal to
  read the durable file.
- **Single transport**: `core/shell-scripts/send-and-verify.sh` — the
  ClawSeat-level transport (shared with gstack-harness, not gstack-owned).
  Never use raw `tmux send-keys` for protocol messages.
- **Audit single-source-of-truth**: every dispatch / deliver / report
  appends to `~/.cartooner/projects/<id>/generation_log.jsonl`.
- **Fail-closed**: if `report_to_memory.py` exits non-zero, the seat aborts.
  We prefer no action over an unrecorded action.

## 2. Two Dispatch Primitives

memory uses one of two primitives depending on the work shape:

### 2.1 `spawn_lane.py` — multi-candidate tournament

For work that produces N parallel candidates the user (or auto-mode picker)
will choose among.

| Receiver | Output | Example |
|---|---|---|
| `builder-image` | N image assets | "4 close-ups of shot-1, low-key lighting" |
| `builder-av` | N video / audio assets | "3 BGM variations, 国风暗黑 mood" |
| `writer` | N text assets (narrative / lyric / copy) | "4 hooks for the 30s ad" |

Closure: each candidate calls `deposit_asset.py`; memory runs `pick_winner.py`.

### 2.2 `dispatch_brief.py` — single-deliverable handoff

For work that produces ONE deliverable: a revision, an analysis, an authoring
task, or any non-tournament dispatch.

| Receiver | Output | Example |
|---|---|---|
| `writer` | revised narrative_outline.md | "rewrite shot 3 dialog with more menace" |
| `builder-av` | revised shot_list.toml | "shot 5 → wide-shot, 8s duration" |
| `builder-av` | reference_learning subagent report | "ingest @youtube/wkw/itmfl for shot rhythm" |
| `builder-image` | character DNA bible | "lock the protagonist's three-view" |

Closure: receiver calls `deliver_brief.py --brief-id <id> --output-path <path>`.

**Choice rule**: if memory anticipates more than one acceptable answer
for the producer to choose among, use spawn_lane. Otherwise dispatch_brief.

## 3. Brief File Format

`~/.cartooner/projects/<id>/briefs/<brief-id>.toml`:

```toml
+++
id = "brief-<8 hex>"
project = "clawseat-anime-test"  # canonical anchor (#8); receiver MUST pass --project = this
created_at = "<iso>"
source = "memory"               # always; cross-seat lateral is forbidden
target = "writer"               # writer | builder-image | builder-av
intent = "lyric"                # high-level: narrative | lyric | copy | shot_list_revision | reference_learning | dna | other
parent_lane = ""                # optional, when brief is part of a lane iteration
parent_shot = ""                # optional, shot_list join key
deliverable_paths = ["narrative_outline.md"]  # list; each path relative to project root
dispatch_session = "cartooner-video-memory-claude"  # dispatcher's tmux session (#9); deliver_brief uses for return-wakeup
state = "open"                  # open | delivered | failed | cancelled
+++

# Brief

(markdown body — full instructions, references, constraints, acceptance criteria)
```

**Multi-deliverable briefs** (audit finding #9, 2026-05-11): `deliverable_paths`
is a list. Pass `--deliverable-path` once per file when calling
`dispatch_brief.py`; the receiver delivers all expected files via repeated
`--output-path` on `deliver_brief.py`. The receiver script enforces basename
coverage: missing any expected file is a fail-closed protocol error. Use
this for tightly-coupled small text deliverables (a workflow comprehension
note + a sample premise; a narrative + its outline header; etc.). For
N-candidate parallel work where the producer picks among options, still
use `spawn_lane` instead.

**dispatch_session** (audit finding #9): the dispatcher's tmux session name,
captured at brief-write time so `deliver_brief.py` can wake the actual
dispatcher pane on return — even when memory's tmux is bound to a
different project than `--project` (cross-project dispatches like
clawseat-anime-test driven by memory in cartooner-video). dispatch_brief
auto-detects from `$TMUX` + `tmux display-message -p '#S'`; pass
`--dispatch-session` explicitly to override.

Parse: split on `+++` markers (frontmatter style, Hugo / Zola convention).
The TOML fields are `tomllib`-parseable; the body is plain markdown for
human reading.

## 4. Push Main Path

```
[memory]
1. memory writes briefs/<id>.toml (durable)
2. memory subprocess.run([dispatch_brief.py, ...])
   ↓
   dispatch_brief.py:
     - validates payload + writes brief file (idempotent)
     - records to PROJECT_INDEX.briefs[<id>]
     - appends generation_log event=brief_dispatched
     - invokes core/shell-scripts/send-and-verify.sh to wake target seat
3. memory continues with other state work; does not block on delivery

[target seat — e.g. writer]
4. wakes via tmux signal
5. reads briefs/<id>.toml frontmatter + body
6. executes (writes deliverable to deliverable_path)
7. subprocess.run([deliver_brief.py, ...]):
     - validates each --output-path file exists + is non-empty UTF-8 (text-only constraint)
     - if brief.deliverable_paths set: enforces basename coverage (missing any expected file is fail-closed)
     - flips brief state=delivered + writes result.outputs = [{path, output_size_chars, file_size}, ...]
       (plus back-compat single-output fields output_path / output_size_chars / file_size mirroring outputs[0])
     - appends generation_log event=brief_delivered
     - resolves wakeup target: --target-session arg → brief.dispatch_session → resolve_seat_session(project, "memory")
     - invokes send-and-verify.sh back to memory pane

[memory]
8. wakes via tmux signal
9. reads brief result + deliverable
10. dispatches downstream (e.g., narrative_outline → spawn_lane builder-av for shot-list authoring)
```

## 5. Pull Fallback

If a wakeup is missed (target seat was busy / restarted / killed mid-run),
memory's recovery path:

```bash
render_asset_tree.py --project <p> | grep "briefs:"
# → list of open briefs older than threshold
```

For each stale brief, memory:
- Re-invokes send-and-verify.sh (same brief id, idempotent on durable file)
- Or escalates via `escalate_to_producer.py --trigger sla_breach --context "brief <id>"`

## 6. Intent Vocabulary

The 6 cartooner-creative intents:

| Intent | Direction | Meaning | Durable anchor |
|---|---|---|---|
| **lane_spawned** | memory → builder-* / writer | N-candidate tournament work assigned | lanes/<id>.toml |
| **brief_dispatched** | memory → any seat | single-deliverable handoff assigned | briefs/<id>.toml |
| **asset_deposited** | builder-* / writer → memory | one candidate landed in a lane | PROJECT_INDEX.assets[<id>] |
| **brief_delivered** | any seat → memory | single deliverable closed | briefs/<id>.toml state=delivered |
| **user_direct_request** | any seat → memory | seat received user-direct, must report fail-closed | generation_log + auto-flip to manual |
| **escalate_to_producer** | memory / patrol → user | auto mode hit a wall | escalations/<id>.toml |

Plus 5 lifecycle helpers (`subagent_spawned` / `subagent_completed` /
`subagent_failed` / `lane_completed` / `shot_list_revised`) used inside
`report_to_memory.py` and `spawn_subagent.py` to hang fine-grained signals
on the same audit timeline.

## 7. Cross-modal Hub-and-Spoke (Q4: memory routes)

cartooner-harness explicitly routes cross-modal work through memory, NOT
peer-to-peer:

```
                user
                 ↓ ↑
               memory  ←─── single point of routing
              ↓ ↑ ↓ ↑ ↓ ↑
       writer | b-image | b-av | patrol
```

**Forbidden**: writer dispatches direct to builder-av ("here's the lyrics,
go make audio"). **Required**: writer delivers to memory; memory inspects
the artifact, optionally augments with style_bible_ref / character_dna_ref,
then dispatches builder-av with a fresh brief or lane.

**Why**: Vision Steward's identity is "single source of truth" — direct
peer dispatch creates parallel state that memory wasn't notified of,
breaking audit + Producer-centric override (user must always be able to
intercept at memory). Cost: one extra hop per cross-modal step. Worth it.

## 8. User-Direct Override

User may bypass memory and instruct any seat directly (per
`user-direct-contract.md`). The receiving seat MUST call
`report_to_memory.py --event user_direct_request` fail-closed. memory
auto-flips `automation_mode` to `manual` on `user_direct_received` (per
`escalate_on` triggers in `automation-mode.md`).

After report_to_memory succeeds, the seat may either:
- Self-spawn a lane (`spawn_lane.py --triggered-by user_direct --actor <self>`), OR
- Self-write a brief and proceed (with `--triggered-by user_direct`)

Then deliverable closure follows normal `deposit_asset` / `deliver_brief`
paths. No silent backchannel.

## 9. Forbidden Patterns

| Pattern | Why forbidden |
|---|---|
| `tmux send-keys` raw protocol message | bypasses transport audit + buffer verification |
| writer → builder-av direct dispatch | breaks memory's SSOT (Q4: hub-and-spoke required) |
| Patrol mutation dispatch | patrol is read-only Asset Guardian |
| Brief without source=memory (except after user_direct report) | breaks dispatcher invariant |
| Multi-deliverable brief used as cheap parallelism | use spawn_lane when producer picks among N candidates; deliverable_paths is for *required* coupled text outputs only |
| Brief body containing image bytes / base64 | text-only constraint; subagent path for vision |

Patrol audits violations by scanning `generation_log.jsonl` for
`brief_dispatched` events with `source != "memory"` (without a preceding
`user_direct_request` from the same seat).

## 10. References

- [`lane-model.md`](lane-model.md) — lane state machine + payload schema
- [`user-direct-contract.md`](user-direct-contract.md) — Producer override + report contract
- [`automation-mode.md`](automation-mode.md) — escalate_on triggers + manual / auto symmetry
- [`subagent-protocol.md`](subagent-protocol.md) — vision-isolated analysis (root_cause / reference_learning)
- gstack-harness analog: [`../../gstack-harness/references/communication-protocol.md`](../../gstack-harness/references/communication-protocol.md)
