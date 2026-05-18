# extract_links.py Typed Link Extraction

`extract_links.py` is a deterministic, zero-LLM extractor for memory pages.
It reads one `.md` or `.json` file, extracts typed references, writes the
source's outgoing links under `_links/`, and reconciles incoming backlinks under
`_backlinks/`.

## Edge Types

The active P1 edge types are:

| Edge type | Target namespace | Examples |
|---|---|---|
| `references-task` | `entity:taskid:<id>` | `TASK-123`, `ARENA-228`, `GH#123`, `#123` |
| `references-commit` | `entity:commit:<sha>` | `commit abc1234`, `merged abc1234`, `cherry-picked abc1234`, `(abc1234)` |
| `references-file` | `entity:file:<path>` | `foo.bar.py`, `scripts/install.sh`, `src/App.tsx` |
| `references-component` | `entity:component:<name>` | `PhysicsEngine`, `ViewLayer`, `PretextComponent` |
| `references-url` | `entity:url:<url>` | `https://github.com/KaneOrca/ClawSeat` |
| `references-key` | `entity:key:<value>` | `[KEY: boundary]`, `[KEY: 边界]` |
| `references-project` | `entity:project:<name>` | `~/.agents/memory/projects/install` |

Freeform `mentions` extraction is intentionally not emitted in P1 because it
has high false-positive risk without a project-specific dictionary.

## False-Positive Controls

- Naked hexadecimal strings are not treated as commits. Commit extraction is
  context-gated to explicit forms such as `commit abc1234`, `merged abc1234`,
  `cherry-picked abc1234`, or parenthesized standalone `(abc1234)`.
- Fenced code blocks are stripped before regex matching. Paths or imports inside
  fenced blocks should not produce file or component edges.
- URL matching stops before common Markdown closing punctuation.

## Component Suffix Configuration

Component suffixes are config-loadable:

1. Project override:
   `~/.agents/memory/projects/<project>/component-patterns.toml`
2. User default:
   `~/.agents/memory/config/component-patterns.toml`
3. Bundled fallback in `extract_links.py`

Example:

```toml
[component_patterns]
suffixes = ["Phasic", "Physics", "View", "Engine", "Layer", "Component"]
```

The extractor seeds the user default file on best effort if no config exists.

## Deduplication

Edges are deduplicated per `(source, target, type)` before being returned and
written. Five mentions of `TASK-123` in one page therefore produce one outgoing
edge and one backlink entry for that source.
