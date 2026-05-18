#!/usr/bin/env python3
"""
memory_deliver.py — single-call delivery for Memory CC.

Wraps the two-step completion flow (write response JSON + call
complete_handoff) into one subprocess invocation. Memory CC's SKILL.md
only has to teach the model to call this script once. All file layout,
schema placement, and harness protocol details stay inside this wrapper.

Usage (inline JSON, preferred):
    python3 memory_deliver.py \\
      --profile ~/.agents/profiles/memory-test-profile.toml \\
      --task-id MEMORY-QUERY-XXX \\
      --target memory-client \\
      --response-inline '{"query_id": "...", "claims": [...], ...}'

Usage (response from file):
    python3 memory_deliver.py \\
      --profile <toml> --task-id XXX --target Y \\
      --response-file /tmp/response.json

Exit codes:
    0 = response written + complete_handoff succeeded
    2 = bad input (missing args, invalid JSON)
    3 = response written but complete_handoff failed (see stderr)
"""
from __future__ import annotations

import argparse
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path


def _real_user_home() -> Path:
    """Bypass sandbox HOME redirection (same trick as scan_environment.py)."""
    try:
        real = Path(pwd.getpwuid(os.getuid()).pw_dir)
        if real.is_dir():
            return real
    except (KeyError, OSError):  # silent-ok: pwd lookup unavailable; fall back to HOME env or Path.home()
        pass
    env_home = os.environ.get("HOME")
    return Path(env_home) if env_home else Path.home()


HOME = _real_user_home()
MEMORY_DIR = HOME / ".agents" / "memory"
RESPONSES_DIR = MEMORY_DIR / "responses"

# complete_handoff.py lives in gstack-harness/scripts/, sibling of this file's
# parent skill dir.
SCRIPT_DIR = Path(__file__).resolve().parent
CLAWSEAT_ROOT = SCRIPT_DIR.parents[3]
COMPLETE_HANDOFF = (
    CLAWSEAT_ROOT / "core" / "skills" / "gstack-harness" / "scripts" / "complete_handoff.py"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Memory CC single-call delivery — write response JSON + call complete_handoff."
    )
    p.add_argument("--profile", required=True, help="Project profile TOML path.")
    p.add_argument("--task-id", required=True, help="Task id (must match the dispatched TODO).")
    p.add_argument(
        "--target",
        required=True,
        help="Who asked (original TODO source). "
             "Seat name (koder/planner/...) → tmux notify; "
             "external (memory-client/...) → skip notify.",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--response-inline", help="Response JSON string (will be parsed + re-serialized).")
    g.add_argument("--response-file", help="Path to pre-written response JSON file.")
    p.add_argument(
        "--summary",
        default="",
        help="Delivery summary for complete_handoff; auto-generated if omitted.",
    )
    return p.parse_args()


def load_response(args: argparse.Namespace) -> dict:
    if args.response_inline:
        try:
            return json.loads(args.response_inline)
        except json.JSONDecodeError as exc:
            print(f"error: --response-inline is not valid JSON: {exc}", file=sys.stderr)
            raise SystemExit(2)
    if args.response_file:
        p = Path(args.response_file).expanduser()
        if not p.is_file():
            print(f"error: --response-file not found: {p}", file=sys.stderr)
            raise SystemExit(2)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"error: --response-file is not valid JSON: {exc}", file=sys.stderr)
            raise SystemExit(2)
    raise SystemExit(2)  # unreachable — argparse guarantees one of the two


def main() -> int:
    args = parse_args()
    response = load_response(args)

    # Ensure query_id matches task_id (auto-patch if missing/wrong)
    response["query_id"] = args.task_id

    # ── Step 1: write response JSON ─────────────────────────────────────
    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    response_path = RESPONSES_DIR / f"{args.task_id}.json"
    response_path.write_text(
        json.dumps(response, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        os.chmod(response_path, 0o600)
    except OSError:  # silent-ok: chmod is best-effort on read-only or cross-platform filesystems
        pass
    print(f"response_written: {response_path}")

    # ── Step 2: call complete_handoff ───────────────────────────────────
    claims = response.get("claims", [])
    claim_count = len(claims) if isinstance(claims, list) else 0
    confidence = response.get("confidence", "unknown")
    summary = args.summary or (
        f"Wrote responses/{args.task_id}.json with {claim_count} claims "
        f"(confidence={confidence})."
    )

    cmd = [
        "python3", str(COMPLETE_HANDOFF),
        "--profile", args.profile,
        "--source", "memory",
        "--target", args.target,
        "--task-id", args.task_id,
        "--status", "completed",
        "--summary", summary,
    ]
    # complete_handoff expands ~ via Path.home() which returns the sandbox
    # home when Memory CC runs it. Override HOME so every ~/... path in the
    # profile / receipt writing resolves to the real user home.
    env = {**os.environ, "HOME": str(HOME)}
    result = subprocess.run(cmd, capture_output=False, check=False, env=env)
    if result.returncode != 0:
        print(
            f"error: complete_handoff failed (rc={result.returncode}); "
            f"response JSON is at {response_path} — manual retry with:\n  "
            f"{' '.join(cmd)}",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
