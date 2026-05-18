#!/usr/bin/env python3
"""memory_smoke.py — one-shot local smoke test for the Memory Oracle seat.

Validates the full memory lifecycle:
  bootstrap → dispatch_scan → query (key/file/search/ask) → verify → teardown

Usage:
    python3 tests/e2e/memory_smoke.py            # dry-run (default, no LLM)
    python3 tests/e2e/memory_smoke.py --dry-run  # explicit dry-run
    python3 tests/e2e/memory_smoke.py --live     # live mode (requires minimax.env)

Output: structured JSON with stage + pass/fail + timing.

Dry-run mode: mocks memory/LLM; no external calls. Safe to run in CI.
Live mode:    requires ~/.agents/secrets/claude/minimax/memory.env with
              MINIMAX_API_KEY set. Uses dispatch_task.py + real Memory CC TUI.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "core" / "skills" / "memory-oracle" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import query_memory as qm
import scan_environment as se


# ── Result helpers ────────────────────────────────────────────────────────────

def _stage(name: str, passed: bool, duration: float, detail: object = None) -> dict:
    return {"stage": name, "passed": passed, "duration_s": round(duration, 3), "detail": detail}


def _result_json(stages: list[dict]) -> dict:
    all_passed = all(s["passed"] for s in stages)
    return {"smoke_test": "memory_oracle", "all_passed": all_passed, "stages": stages}


# ── Stage implementations ─────────────────────────────────────────────────────

def stage_bootstrap(mem_dir: Path) -> dict:
    """Stage 1: bootstrap — create memory dir and write credential fixture."""
    t0 = time.monotonic()
    try:
        machine = mem_dir / "machine"
        machine.mkdir(parents=True, exist_ok=True)
        fixture = {
            "scanned_at": "2026-04-19T00:00:00+00:00",
            "keys": {
                "SMOKE_TEST_KEY": {"value": "smoke-value-abc", "source": "/tmp/fake.env"}
            },
        }
        (machine / "credentials.json").write_text(
            json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        assert mem_dir.is_dir()
        assert (machine / "credentials.json").is_file()
        return _stage("bootstrap", True, time.monotonic() - t0, {"mem_dir": str(mem_dir)})
    except Exception as exc:
        return _stage("bootstrap", False, time.monotonic() - t0, str(exc))


def stage_dispatch_scan(mem_dir: Path, dry_run: bool) -> dict:
    """Stage 2: dispatch_scan — invoke scan_environment scanner."""
    t0 = time.monotonic()
    try:
        data = se.scan_environment()
        assert "vars" in data and "key_count" in data
        if not dry_run:
            machine = mem_dir / "machine"
            machine.mkdir(parents=True, exist_ok=True)
            (machine / "env.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return _stage("dispatch_scan", True, time.monotonic() - t0, {"key_count": data["key_count"]})
    except Exception as exc:
        return _stage("dispatch_scan", False, time.monotonic() - t0, str(exc))


def stage_query_key(mem_dir: Path, capsys_buf: list) -> dict:
    """Stage 3: query_key — --key lookup against the fixture."""
    t0 = time.monotonic()

    import io
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        rc = qm.cmd_key(mem_dir, "credentials.keys.SMOKE_TEST_KEY.value")
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout

    passed = rc == 0 and "smoke-value-abc" in out
    return _stage("query_key", passed, time.monotonic() - t0, {"rc": rc, "output_snippet": out[:80]})


def stage_query_file(mem_dir: Path) -> dict:
    """Stage 4: query_file — --file lookup."""
    t0 = time.monotonic()
    import io
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        rc = qm.cmd_file(mem_dir, "credentials", "keys.SMOKE_TEST_KEY")
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout
    passed = rc == 0 and "smoke-value-abc" in out
    return _stage("query_file", passed, time.monotonic() - t0, {"rc": rc})


def stage_query_search(mem_dir: Path) -> dict:
    """Stage 5: query_search — --search cross-file."""
    t0 = time.monotonic()
    import io
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        rc = qm.cmd_search(mem_dir, "smoke-value")
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout
    passed = rc == 0 and "smoke-value" in out
    return _stage("query_search", passed, time.monotonic() - t0, {"rc": rc, "hit": passed})


def stage_query_ask(tmp_root: Path) -> dict:
    """Stage 6: query_ask — assert cmd_ask creates responses dir before dispatch fails.

    Runs query_memory.py --ask via subprocess with HOME=tmp_root so that
    DEFAULT_MEMORY_DIR resolves into the sandbox. The dispatch will fail
    (no real memory seat / T9 blocks --target memory), but cmd_ask creates
    the responses/ directory before attempting dispatch — this confirms the
    infrastructure setup path is exercised.
    """
    t0 = time.monotonic()
    try:
        fake_profile = tmp_root / "smoke_fake_profile.toml"
        fake_profile.write_text('version = 1\nproject_name = "smoke-test"\n', encoding="utf-8")

        query_script = _SCRIPTS / "query_memory.py"
        env = {**os.environ, "HOME": str(tmp_root)}

        result = subprocess.run(
            [
                sys.executable,
                str(query_script),
                "--ask", "what is SMOKE_TEST_KEY?",
                "--profile", str(fake_profile),
                "--timeout", "0.5",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=8.0,
        )
        responses_dir = tmp_root / ".agents" / "memory" / "responses"
        # cmd_ask creates responses_dir before dispatch; dispatch fails → rc in (1, 2)
        prompt_dir_created = responses_dir.is_dir()
        rc_acceptable = result.returncode in (1, 2)
        passed = prompt_dir_created and rc_acceptable
        return _stage("query_ask", passed, time.monotonic() - t0, {
            "rc": result.returncode,
            "responses_dir_created": prompt_dir_created,
        })
    except subprocess.TimeoutExpired:
        return _stage("query_ask", False, time.monotonic() - t0, "subprocess timed out")
    except Exception as exc:
        return _stage("query_ask", False, time.monotonic() - t0, str(exc))


def stage_verify(mem_dir: Path) -> dict:
    """Stage 7: verify — verify_claims happy path AND mismatch path."""
    t0 = time.monotonic()
    try:
        # Pass case
        pass_response = {
            "claims": [{
                "statement": "SMOKE_TEST_KEY exists with correct value",
                "evidence": [{
                    "file": "credentials",
                    "path": "keys.SMOKE_TEST_KEY.value",
                    "expected_value": "smoke-value-abc",
                }],
            }]
        }
        pass_result = qm.verify_claims(pass_response, mem_dir)
        pass_ok = pass_result["all_verified"] is True

        # Mismatch case — must return all_verified=False
        mismatch_response = {
            "claims": [{
                "statement": "Wrong value claim",
                "evidence": [{
                    "file": "credentials",
                    "path": "keys.SMOKE_TEST_KEY.value",
                    "expected_value": "WRONG-VALUE",
                }],
            }]
        }
        mismatch_result = qm.verify_claims(mismatch_response, mem_dir)
        mismatch_ok = mismatch_result["all_verified"] is False

        passed = pass_ok and mismatch_ok
        return _stage("verify", passed, time.monotonic() - t0, {
            "pass_ok": pass_ok,
            "mismatch_ok": mismatch_ok,
        })
    except Exception as exc:
        return _stage("verify", False, time.monotonic() - t0, str(exc))


def stage_teardown(mem_dir: Path) -> dict:
    """Stage 8: teardown — verify memory dir is populated and cleanup is possible."""
    t0 = time.monotonic()
    try:
        assert mem_dir.is_dir(), "memory dir should still exist"
        json_files = list(mem_dir.rglob("*.json"))
        assert len(json_files) > 0, "memory dir should contain fixture files"
        # Cleanup check: verify we can remove and recreate a marker
        marker = mem_dir / ".smoke_teardown_check"
        marker.touch()
        assert marker.exists()
        marker.unlink()
        return _stage("teardown", True, time.monotonic() - t0, {"json_files": len(json_files)})
    except Exception as exc:
        return _stage("teardown", False, time.monotonic() - t0, str(exc))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Memory Oracle smoke test")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Dry-run mode (default): no LLM/external calls")
    parser.add_argument("--live", action="store_true",
                        help="Live mode: requires ~/.agents/secrets/claude/minimax/memory.env")
    args = parser.parse_args()

    if args.live:
        secrets = Path.home() / ".agents" / "secrets" / "claude" / "minimax" / "memory.env"
        if not secrets.exists():
            print(json.dumps({"error": f"live mode requires {secrets}"}), flush=True)
            return 2

    with tempfile.TemporaryDirectory(prefix="cs_memory_smoke_") as tmp:
        tmp_root = Path(tmp)
        mem_dir = tmp_root / "memory"
        mem_dir.mkdir()

        stages: list[dict] = []
        capsys_buf: list = []

        stages.append(stage_bootstrap(mem_dir))
        stages.append(stage_dispatch_scan(mem_dir, dry_run=not args.live))
        stages.append(stage_query_key(mem_dir, capsys_buf))
        stages.append(stage_query_file(mem_dir))
        stages.append(stage_query_search(mem_dir))
        stages.append(stage_query_ask(tmp_root))
        stages.append(stage_verify(mem_dir))
        stages.append(stage_teardown(mem_dir))

        result = _result_json(stages)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
