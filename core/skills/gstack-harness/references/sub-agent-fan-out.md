# Sub-agent Fan-out

When a dispatched task has independent sub-goals, the receiving seat/TUI must
parallelize them via sub-agents instead of serializing. This is a default, not
an optimization.

## When to fan out (trigger rules)

Fan-out is **required** if any of the following are true:

1. **Disjoint file sets** — Part A and Part B modify non-overlapping files
   (e.g., Part A touches `scripts/a.sh`, Part B touches `core/b.py`)
2. **Disjoint test targets** — Part A adds/modifies tests in `tests/test_a_*`,
   Part B adds/modifies tests in `tests/test_b_*`, and they don't share
   fixtures under test
3. **Disjoint research queries** — the task is read-only investigation with N
   independent lanes (e.g., audit N `(tool, auth_mode, provider)` combos;
   check N endpoints; diff N versions)
4. **Explicitly named multi-part task** — the task spec labels parts as
   "Part A / Part B / Part C" without stated interdependence

Fan-out is **not required** when:

- Parts share mutable state (e.g., both modify the same config file, the same
  function, or the same test fixture)
- The task is a single short change (<5 minutes estimated wall-clock)
- The receiving tool/agent does not support sub-agents (plain shell workers,
  some minimal Codex profiles)
- Parts must observe each other's intermediate state to be correct
  (e.g., Part B verifies the side-effect of Part A)

## Fan-out pattern

```
1. Split the task brief into N self-contained sub-briefs. Each sub-brief must
   name its own file scope, test targets, and acceptance criteria. A sub-brief
   that says "also coordinate with the other lane" is NOT self-contained —
   split again or keep serial.

2. Spawn N sub-agents in parallel:
   - Claude Code: single message with N `Agent` tool calls
   - Codex: `codex subagent` per lane (launcher-dependent)
   - Gemini: sub-agent task per lane

3. Collect N deliverables. Each sub-agent returns: files touched, tests run,
   verdict (pass/fail/blocked).

4. Serial finalization:
   - Cross-check: do the N deliverables conflict? (shared imports, stale
     snapshots, duplicated logic, etc.)
   - Regression sweep: run the combined test matrix once, not N times
   - Write ONE DELIVERY-*.md summarizing all lanes + the cross-check result
```

## Anti-patterns

- **"I'll do Part A first, then Part B"** when parts are disjoint -> serial
  when you could fan out
- **Fan-out without cross-check** -> two sub-agents independently patch the
  same enum in different files and silently disagree
- **Splitting a single bug fix into fake parallel lanes** -> e.g., "Lane 1:
  change variable name in call site, Lane 2: change variable name in
  definition" — these are one atomic edit
- **Delegating judgment to sub-agents** -> the top-level seat must still
  synthesize the final verdict; sub-agents report, they do not decide

## Example — round-3a codex-xcode (what should have happened)

Task: retire `wait-for-seat.sh` 1-arg form AND fix launcher `--auth xcode`
config.toml rendering.

Disjoint file sets:
- Part A: `scripts/wait-for-seat.sh`, 3 existing tests, 2 docs
- Part B: `core/launchers/agent-launcher.sh`, 2 new tests

Disjoint test targets: `test_wait_for_seat_*` vs `test_launcher_codex_xcode_*`.

Correct execution:

```
parallel:
  agent_A brief: "Retire wait-for-seat.sh 1-arg form.
    Scope: scripts/wait-for-seat.sh + tests + docs.
    Verdict: report files touched + pytest result."

  agent_B brief: "Fix launcher --auth xcode config.toml rendering.
    Scope: core/launchers/agent-launcher.sh + 2 new tests.
    Verdict: report files touched + pytest result."

serial (main):
  1. Read both agent reports
  2. Run combined regression sweep (48 existing tests)
  3. Write DELIVERY-ROUND3-XCODE-CONFIG-AND-1ARG-RETIRE.md merging both
```

Wall-clock savings: ~40-50% on the per-part investigate+implement+test loop.

## Example — audit/investigation (round-3c gemini)

Task: audit N combinations in `SUPPORTED_RUNTIME_MATRIX` against launcher
case-branches.

Each combo is an independent verification lane — no shared mutable state, no
cross-combo dependencies.

Correct execution:

```
parallel:
  agent_1: verify claude+oauth+anthropic against launcher
  agent_2: verify claude+api+minimax against launcher
  agent_3: verify codex+api+xcode-best against launcher
  ...
  agent_N: verify gemini+oauth+google against launcher

serial (main):
  1. Collect N verdicts
  2. Cluster into keep / fix / drop recommendations
  3. Write DIAGNOSIS-MATRIX-AUDIT.md
```

## How this interacts with dispatch_task.py

`dispatch_task.py` writes a `TODO.md` entry for the target seat. When the
dispatching planner knows the task is fan-out-eligible, the `--objective` or
task body should include the explicit instruction:

> "This task has N independent sub-parts. Fan them out to sub-agents; only
> serialize the final cross-check and single DELIVERY write-up."

Planner's default dispatch prompt template (see `dispatch-playbook.md`) must
include a fan-out hint when the task has a Part A / Part B / Part C structure.

## Checklist for the receiving seat

Before starting work, the seat should ask:

- [ ] Are there 2+ named parts in the task brief?
- [ ] Do the parts touch disjoint files?
- [ ] Do the parts modify disjoint test targets?
- [ ] Is any part >5 minutes of estimated work?

If any ONE is "yes", **fan out** — this mirrors the trigger rules at the top of this document (any single trigger makes fan-out required). If all are "no", proceed serial.

Do not soften the rule into "you need two yes" — that contradicts the trigger rules. The checklist is a convenience re-framing of the trigger rules, not a stricter variant.
