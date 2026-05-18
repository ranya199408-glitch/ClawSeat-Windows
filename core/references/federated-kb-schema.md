# Federated KB Schema

ClawSeat uses a federated knowledge model: each seat owns its domain KB, and
Memory reads those KBs directly to synthesize cross-seat knowledge. Memory is
not the sole store of project knowledge.

## Memory Workspace Layout

```text
~/.agents/memory/                        ← global KB root
├── machine/<*.json>                     ← M1 scanner credentials/network/openclaw/github/current_context
├── learnings/                           ← cross-project patterns when present
├── shared/                              ← shared library knowledge and examples
├── index.json                           ← global scan_index.py summary
├── events.log                           ← global append-only JSONL event stream
├── responses/<task_id>.json             ← memory_deliver.py outputs
└── projects/<project>/                  ← see Project Layout
```

## Project Layout

```text
~/.agents/memory/projects/<project>/
├── dev_env.json                         ← M2 scanner shallow output
├── decision/<ts>-<slug>.md              ← Memory decisions, orphan knowledge
├── finding/<ts>-<slug>.md               ← Memory findings, orphan knowledge
├── task/<ts>-<slug>.md                  ← Memory task records, orphan knowledge
├── plan/<ts>-<slug>.md                  ← Memory plans, optional orphan knowledge
├── reviewer/findings/<ts>-<slug>.md      ← Reviewer QA findings
├── builder/<ts>-<slug>.md               ← Builder domain KB
├── planner/<ts>-<slug>.md               ← Planner domain KB
├── reviewer/<ts>-<slug>.md              ← Reviewer domain KB
├── patrol/doc-code-alignment/<ts>-<slug>.md
├── patrol/test-results/<ts>-<slug>.md
├── patrol/task-commit-gaps/<ts>-<slug>.md
└── _index/                              ← scan_index.py derivative output
```

## Path Conventions

Seat KBs live under the Memory project tree:

```text
~/.agents/memory/projects/<project>/
├── builder/<ts>-<slug>.md
├── planner/<ts>-<slug>.md
├── reviewer/<ts>-<slug>.md
├── reviewer/findings/<ts>-<slug>.md
├── patrol/doc-code-alignment/<ts>-<slug>.md
├── patrol/test-results/<ts>-<slug>.md
├── patrol/task-commit-gaps/<ts>-<slug>.md
└── decision/<ts>-<slug>.md
```

Concrete paths:

- `~/.agents/memory/projects/<project>/builder/<ts>-<slug>.md`
- `~/.agents/memory/projects/<project>/planner/<ts>-<slug>.md`
- `~/.agents/memory/projects/<project>/reviewer/<ts>-<slug>.md`
- `~/.agents/memory/projects/<project>/reviewer/findings/<ts>-<slug>.md`
- `~/.agents/memory/projects/<project>/patrol/doc-code-alignment/<ts>-<slug>.md`
- `~/.agents/memory/projects/<project>/patrol/test-results/<ts>-<slug>.md`
- `~/.agents/memory/projects/<project>/patrol/task-commit-gaps/<ts>-<slug>.md`
- `~/.agents/memory/projects/<project>/decision/<ts>-<slug>.md`

Project identity and repo location come from `~/.clawseat/projects.json`. When a
seat needs repo files, resolve the project through its `repo_path` field, then
read project-local docs and code from that repo.

## Record Format

Every KB record is one Markdown file with YAML-style frontmatter and a free
Markdown body:

```markdown
---
issue_id: uuid
ts: 2026-04-27T18:30:00Z
task_id: task-id
project: install
seat: builder|planner|reviewer|patrol|memory
kind: decision|finding|alignment|test_result|observation
title: "Short title"
status: open|resolved|completed|superseded
detail: "One-line summary"
---

Free Markdown body with details, evidence, links, or longer notes.
```

The public fields live in frontmatter:

- `issue_id`
- `ts`
- `task_id`
- `project`
- `seat`
- `kind`
- `title`
- `status`
- `detail`

Seat-specific records may add fields. Recommended additions:

- Builder: `decision_type`, `files_affected`, `constraints`
- Planner: `decision_type`, `alternatives_considered`, `priority_reason`
- Reviewer: `risk_type`, `severity`
- QA: `doc_file`, `code_file`, `issue_type`, `severity`, `first_seen`,
  `last_seen`, `resolved_at`, `model`

### reviewer/findings/<ts>-<slug>.md

Frontend/browser review findings written by reviewer QA mode use this sub-path:

```markdown
---
task_id: task-id
severity: HIGH | MEDIUM | LOW
url: https://host/path
repro: step-by-step repro steps
screenshot_path: null | /abs/path/to/screenshot.png
status: open | investigating | resolved
---

Free-form description (keep under 200 words).
```

## Memory Read Protocol

- Memory reads seat KB files directly from disk.
- There is no message protocol for KB reads.
- Memory resolves project paths through `projects.json` and then reads
  `~/.agents/memory/projects/<project>/`.
- Memory does not write into another seat's KB.
- When Memory synthesizes cross-seat conclusions, it writes only to its own
  Memory KB or event log.
- If a seat KB directory is missing, Memory treats that as
  `not_in_federated_kb` for that seat, not as a fatal error.

## Retention Rules

- Markdown KB records are append-only at the record level.
- Do not delete historical observations.
- Resolved or completed facts are represented with status fields such as
  `resolved`, `completed`, or `superseded`.
- If a known issue is seen again, append or update according to the owning
  seat's documented rule, but preserve the original `first_seen` timestamp.

## Ownership

- Builder owns implementation decisions and technical constraints.
- Planner owns dispatch, priority, and alternative-selection decisions.
- Reviewer owns review observations and recurring risk patterns.
- QA owns doc-code alignment, task-commit gaps, and test results.
- Memory owns orphan knowledge: cross-seat synthesis, north-star deviation judgment,
  user clarification records, and major event chains.
