# tests/e2e — End-to-End Smoke Tests

Standalone scripts (not pytest) that validate full lifecycle flows.
Each script outputs structured JSON: `{"all_passed": bool, "stages": [...]}`.

## memory_smoke.py — Memory Oracle Smoke Test

Validates the full memory lifecycle without the MiniMax LLM API:

```
bootstrap → dispatch_scan → query (key/file/search/ask) → verify → teardown
```

### Dry-run mode (default, CI-safe)

```bash
python3 tests/e2e/memory_smoke.py
# or explicitly:
python3 tests/e2e/memory_smoke.py --dry-run
```

No external calls. Uses a tmp directory; cleans up after itself.
Exit 0 = all stages passed. Output is valid JSON.

### Live mode (requires minimax.env)

```bash
python3 tests/e2e/memory_smoke.py --live
```

Requires `~/.agents/secrets/claude/minimax/memory.env` containing `MINIMAX_API_KEY`.
Dispatches a real query to the Memory CC TUI via `dispatch_task.py`.
Do not run in CI unless the secret is available.

## Dependencies

### Required for dry-run

| Dependency | Notes |
|---|---|
| Python ≥ 3.11 | Required |
| `query_memory.py` (in-repo) | Imported directly |
| `scan_environment.py` (in-repo) | Imported directly |

### Required for live mode only

| Dependency | Notes |
|---|---|
| MiniMax API key | `~/.agents/secrets/claude/minimax/memory.env` |
| `dispatch_task.py` (in-repo) | Called via subprocess |

### Optional

| Dependency | Install | Notes |
|---|---|---|
| `pytest-cov` | `pip install pytest-cov` | Needed for `coverage report` on the memory-oracle module (T10 R8 coverage check) |

No third-party pip packages required for dry-run mode.

## Known Issues

- **coverage report fails without pytest-cov**: If `pytest --cov=...` fails with `no module named pytest_cov`, install with `pip install pytest-cov` (or `pip3 install --break-system-packages pytest-cov` on Homebrew-managed Python).
- **query_ask stage fails if dispatch blocked**: The `query_ask` stage runs `query_memory.py --ask` in a sandbox HOME. It asserts that the responses directory is created, then dispatch fails (expected, as T9 blocks `--target memory`). This is intentional — the stage verifies infrastructure setup, not a live dispatch.

## Adding New Smoke Tests

- Place scripts in this directory.
- Output structured JSON: `{"smoke_test": "<name>", "all_passed": bool, "stages": [...]}`
- Support `--dry-run` (default) and optional `--live`.
- Document dependencies in this README.
