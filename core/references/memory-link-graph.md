# Memory Typed-Link Graph (v0.9, P1)

> Deterministic regex extraction from memory pages. Zero LLM calls, zero
> embedding cost. The graph is the carry — vector / FTS upgrades come later
> if the graph alone proves insufficient.

## Why a graph

ClawSeat memory is federated markdown — each seat owns its KB directory.
Cross-document recall used to mean grep + reading mtimes. The link graph
adds a derivative index that answers two real questions:

- **Backlinks**: who linked to this page or this entity? (e.g. who mentioned
  ARENA-228 across all seats?)
- **Graph traversal**: what's reachable from this page within N hops?

Inspired by gbrain's "graph is carry, vector is icing" benchmark
(P@5 49.1 → graph-disabled 17.7 on the same corpus). We adopt the graph
half; we do not adopt vector embeddings, the postgres dependency, or the
Bun runtime.

## On-disk layout

```text
~/.agents/memory/
├── projects/<project>/...                ← source pages (.md / .json)
├── _links/<flat-source>.jsonl            ← outgoing edges from one source
└── _backlinks/<flat-target>.jsonl        ← incoming refs to one target
```

`<flat-source>` and `<flat-target>` are filesystem-safe encodings:

| In source slug | Encoded | Reason |
|---|---|---|
| `/` | `__` | path separator collapses to flat name |
| `:` | `++` | namespace separator for `entity:<ns>:<val>` |

Example:

| Slug | Flat |
|---|---|
| `projects/arena/decision/foo` | `projects__arena__decision__foo` |
| `entity:taskid:ARENA-228` | `entity++taskid++ARENA-228` |

## Edge schema (one JSON object per line)

Outgoing (`_links/<flat-source>.jsonl`):

```json
{
  "from": "projects/arena/decision/foo",
  "to": "entity:taskid:ARENA-228",
  "type": "references-task",
  "snippet": "...short context window...",
  "extracted_at": "2026-04-29T05:12:00Z"
}
```

Incoming (`_backlinks/<flat-target>.jsonl`) — same fields, "from" is the
referring source page.

## Edge types

| `type` | What it captures | Regex (in `extract_links.py`) |
|---|---|---|
| `references-task` | Jira/GitHub-style task IDs like `ARENA-228` / `T-001` / `GH#123` / `#123` | configured in `BASE_PATTERNS` |
| `references-commit` | git SHAs in explicit commit context | `commit <sha>`, `merged <sha>`, `cherry-picked <sha>`, or `(<sha>)` |
| `references-component` | React / physics components by configured suffix | default suffixes: `Phasic`, `Physics`, `View`, `Engine`, `Layer`, `Component` |
| `references-file` | source paths with known extensions | `\b[a-zA-Z][\w./-]*\.(tsx\|ts\|py\|md\|toml\|sh\|json\|yaml\|yml\|sql\|js)\b` |
| `references-url` | http(s) URLs | `https?://\S+` |
| `references-key` | arena-style decryption keys | `\[KEY:\s*([^\]]+)\]` |
| `references-project` | cross-project memory references | `~/\.agents/memory/projects/([\w-]+)\b` |

Component suffixes are config-loadable from
`~/.agents/memory/projects/<project>/component-patterns.toml` or
`~/.agents/memory/config/component-patterns.toml`.

Add a new non-component edge type → add one tuple to `BASE_PATTERNS` in
`extract_links.py`.

## Idempotency contract

Re-running `extract_links.py` on the same source MUST be safe:

1. Outgoing index for the source is rewritten in full
2. Targets that disappear from the new content are pruned from their
   `_backlinks/<target>.jsonl`. If the file becomes empty it is deleted
3. Targets that appear in the new content append exactly one line per
   source to their backlinks file (existing entries from the same source
   are removed first)

Test coverage: `tests/test_memory_extract_links.py`.

## Hooks

Both write paths in `memory_write.py` call `_update_link_graph` after the
disk write. Failures inside `extract_links.py` are silenced — the graph is
a best-effort derivative; never block writes.

## Query CLI

```bash
# All sources that referenced this entity or page
python3 query_memory.py --backlinks "entity:taskid:ARENA-228"
python3 query_memory.py --backlinks "projects/arena/decision/foo"

# BFS from a slug, configurable depth (default 1)
python3 query_memory.py --graph projects/arena/decision/foo --depth 2
```

Slug normalisation accepts: bare slug, slug with `.md`/`.json` extension,
absolute path under memory root, or `entity:<ns>:<val>` form.

## What this is NOT

- **Not** a database — no schema migrations, no service, no daemon
- **Not** vector search — pure regex match + JSONL storage
- **Not** LLM-driven — nothing in the extract path calls an API
- **Not** authoritative — the source markdown is truth; the graph is
  always rebuildable from sources by re-running `extract_links.py` on
  every page

If you need vector / hybrid search, the natural next step is a sqlite FTS5
table (P2 in the plan), not embeddings — graph + FTS reaches gbrain's
benchmark headline without OpenAI.
