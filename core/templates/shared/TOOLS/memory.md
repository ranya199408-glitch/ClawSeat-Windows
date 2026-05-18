# TOOLS/memory.md — Memory Learning Channel

## L3 Reflector Contract

**Memory CC** is the **L3 Reflector** seat: it records, organises, reflects, and
researches. It is a single-turn oracle — one prompt in, one delivery out. It does
NOT read a task queue (TODO.md), does NOT hold session state, and does NOT
self-initiate work.

- Full capability spec: `core/skills/memory-oracle/SKILL.md`
- Query protocol (T7 canonical): `core/skills/clawseat-install/references/memory-query-protocol.md`

---

## Query vs Learning Request

### Query — direct script call (no seat dispatch)

Use these three modes when you need a **fact that may already be in the knowledge base**:

```bash
# Key lookup
python3 $CLAWSEAT_ROOT/core/skills/memory-oracle/scripts/query_memory.py \
  --key credentials.keys.MINIMAX_API_KEY.value

# Kind/project lookup
python3 $CLAWSEAT_ROOT/core/skills/memory-oracle/scripts/query_memory.py \
  --kind decision --project install

# Episode lookup
python3 $CLAWSEAT_ROOT/core/skills/memory-oracle/scripts/query_memory.py \
  --episode BRIDGE-SMOKE-001 --project install
```

**Do not dispatch to memory for a query** — direct script calls have zero latency,
zero token cost, and cannot hallucinate.

### Learning Request — `notify_seat.py --target memory`

Use when you need memory to **produce new knowledge** (research, pattern extraction,
cross-project synthesis). Dispatch a learning prompt via the notify channel:

```bash
python3 $CLAWSEAT_ROOT/core/skills/gstack-harness/scripts/notify_seat.py \
  --profile <profile.toml> \
  --target memory \
  --message "LEARNING REQUEST: <one-line description of what to extract or research>"
```

Memory processes the prompt in a single turn, writes new facts to
`~/.agents/memory/projects/<project>/`, and replies via `memory_deliver.py`.
The result is available immediately for subsequent direct-script queries.

---

## 6 Caller Examples

### koder
```
LEARNING REQUEST: Collect all AUTO_ADVANCE success patterns from the install
project over the last 7 days — extract trigger conditions, time-to-complete,
and any edge cases into an episode record.
```
→ Memory writes `projects/install/episodes/<id>.json`

### planner
```
LEARNING REQUEST: Compare the T11 workspace split-brain rsync approach vs the
T15 _resolve_effective_home() approach — which invariant each protects, when each
is sufficient, and what residual risk remains after both land.
```
→ Memory writes `projects/install/decisions/<id>.json`

### builder
```
LEARNING REQUEST: Extract the validator design pattern from the retired T18 install validator
— the G1–G15 check dict contract, CRITICAL set, warn_only flag, and how to extend
it for new checks — as a reusable finding for future builders.
```
→ Memory writes `shared/patterns/<id>.json`

### reviewer
```
LEARNING REQUEST: Analyse the two Codex reviewer tomllib false-alarm incidents —
identify the environment-divergence pattern, the canary conditions that misled the
reviewer, and produce a failure-mode record to prevent recurrence.
```
→ Memory writes `shared/examples/failure-mode-<id>.json`

### patrol
```
LEARNING REQUEST: Produce a methodology record: which real-exec steps in merged
QA runs are safely skippable on re-runs (already validated by prior receipt),
and which must always re-run. Tag by check category.
```
-> Memory writes `shared/library_knowledge/patrol-methodology-<id>.json`

### designer
```
LEARNING REQUEST: Assess whether the 7-step Feishu bridge setup docs structure
(prereqs → event-scope checklist → step-by-step → troubleshoot) could be
directly re-applied to the OAuth flow setup — identify any structural mismatches.
```
→ Memory writes `shared/patterns/cross-domain-<id>.json`

---

## When NOT to use the learning channel

| Condition | Correct action |
|---|---|
| Key is already in `~/.agents/memory/` | Use `query_memory.py --key ...` directly |
| You need memory to _run_ code or make commits | It cannot — memory is read-only execution |
| You want memory to notify a third seat | It cannot — memory delivers only to the caller |
| The learning output is needed faster than one turn | Cache the result yourself instead |
