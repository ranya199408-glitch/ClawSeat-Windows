#!/usr/bin/env python3
"""
scan_project.py — scan a project repository and write memory facts (SPEC §5.1 #2).

Usage:
    python3 scan_project.py --project <name> --repo <path> [--depth shallow|medium|deep]
                            [--commit] [--force-commit] [--quiet]

Depth gating (§D15):
    shallow (default) — writes dev_env.json only (flat summary of all detectors)
    medium            — writes dev_env.json + runtime/tests/deploy/ci/lint/structure.json
    deep              — medium + env_templates.json

Dry-run (default):
    Prints what would be written as JSON to stdout; does NOT touch the filesystem.

--commit:
    Actually writes files under projects/<name>/. Fails if files already exist.

--force-commit:
    Like --commit but overwrites existing files.

Exit codes:
    0   success
    1   runtime error (bad repo path, schema validation failure, file exists without --force-commit)
    2   bad CLI usage
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_CORE_LIB = _SCRIPTS.parents[2] / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))

from _memory_paths import (  # noqa: E402
    MEMORY_ROOT,
    generate_id,
    dev_env_path,
    runtime_path,
    tests_path,
    deploy_path,
    ci_path,
    lint_path,
    structure_path,
    env_templates_path,
)
from _memory_schema import SchemaError, make_record, validate  # noqa: E402
from _project_detectors import (  # noqa: E402
    detect_runtime,
    detect_tests,
    detect_deploy,
    detect_ci,
    detect_lint,
    detect_structure,
    detect_env_templates,
)
from utils import now_iso  # noqa: E402


# ── Constants ─────────────────────────────────────────────────────────────────

SHALLOW_KINDS = ("dev_env",)
MEDIUM_KINDS = ("dev_env", "runtime", "tests", "deploy", "ci", "lint", "structure")
DEEP_KINDS = ("dev_env", "runtime", "tests", "deploy", "ci", "lint", "structure", "env_templates")

_KIND_DETECTOR_MAP = {
    "runtime": detect_runtime,
    "tests": detect_tests,
    "deploy": detect_deploy,
    "ci": detect_ci,
    "lint": detect_lint,
    "structure": detect_structure,
    "env_templates": detect_env_templates,
}

_KIND_PATH_MAP = {
    "dev_env": dev_env_path,
    "runtime": runtime_path,
    "tests": tests_path,
    "deploy": deploy_path,
    "ci": ci_path,
    "lint": lint_path,
    "structure": structure_path,
    "env_templates": env_templates_path,
}

_DEPTH_KINDS = {
    "shallow": SHALLOW_KINDS,
    "medium": MEDIUM_KINDS,
    "deep": DEEP_KINDS,
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_dev_env_summary(
    project: str,
    repo_root: Path,
    detector_results: dict[str, dict],
    depth: str,
    ts: str,
) -> dict:
    """Aggregate all detector results into a flat dev_env summary record."""
    runtime = detector_results.get("runtime", {}).get("data", {})
    tests = detector_results.get("tests", {}).get("data", {})
    deploy = detector_results.get("deploy", {}).get("data", {})
    ci = detector_results.get("ci", {}).get("data", {})
    lint = detector_results.get("lint", {}).get("data", {})
    structure = detector_results.get("structure", {}).get("data", {})
    env_tmpl = detector_results.get("env_templates", {}).get("data", {})

    data: dict = {
        # runtime
        "python": runtime.get("python", False),
        "python_version": runtime.get("python_version"),
        "node": runtime.get("node", False),
        "pnpm": runtime.get("pnpm", False),
        "yarn": runtime.get("yarn", False),
        "npm": runtime.get("npm", False),
        "go": runtime.get("go", False),
        "rust": runtime.get("rust", False),
        "ruby": runtime.get("ruby", False),
        "uv": runtime.get("uv", False),
        "poetry": runtime.get("poetry", False),
        "primary_language": runtime.get("primary_language"),
        # tests
        "pytest": tests.get("pytest", False),
        "jest": tests.get("jest", False),
        "vitest": tests.get("vitest", False),
        "playwright": tests.get("playwright", False),
        # deploy
        "has_dockerfile": deploy.get("has_dockerfile", False),
        "has_compose": deploy.get("has_compose", False),
        # ci
        "has_ci": ci.get("has_ci", False),
        "github_actions": ci.get("github_actions", False),
        # lint
        "ruff": lint.get("ruff", False),
        "black": lint.get("black", False),
        "mypy": lint.get("mypy", False),
        "eslint": lint.get("eslint", False),
        "prettier": lint.get("prettier", False),
        # structure
        "has_src": structure.get("has_src", False),
        "has_docs": structure.get("has_docs", False),
        "has_tests_dir": structure.get("has_tests_dir", False),
        # env templates
        "has_env_template": env_tmpl.get("has_env_template", False),
        # meta
        "last_project_scan_depth": depth,
        "repo_root": str(repo_root),
    }

    # Collect all evidence from all detectors
    all_evidence: list[dict] = []
    seen_urls: set[str] = set()
    for det_result in detector_results.values():
        for ev in det_result.get("evidence", []):
            url = ev.get("source_url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                all_evidence.append(ev)

    if not all_evidence:
        all_evidence = [{"source_url": f"file://{repo_root}", "trust": "low"}]

    fact_id = generate_id("dev_env", project, ts)
    record = make_record(
        kind="dev_env",
        project=project,
        author="memory",
        ts=ts,
        title=f"{project} dev_env summary ({depth})",
        fact_id=fact_id,
        body="",
        evidence=all_evidence,
        source="scanner",
        confidence="high",
    )
    record["data"] = data
    return record


def _build_kind_record(
    kind: str,
    project: str,
    ts: str,
    detector_result: dict,
) -> dict:
    """Build a schema v1 record for a single detector kind."""
    data = detector_result.get("data", {})
    evidence = detector_result.get("evidence", [])
    if not evidence:
        evidence = [{"source_url": f"file://unknown", "trust": "low"}]

    fact_id = generate_id(kind, project, ts)
    record = make_record(
        kind=kind,
        project=project,
        author="memory",
        ts=ts,
        title=f"{project} {kind} scan",
        fact_id=fact_id,
        body="",
        evidence=evidence,
        source="scanner",
        confidence="high",
    )
    record["data"] = data
    return record


def _validate_record(record: dict) -> None:
    """Validate; raise SystemExit on SchemaError."""
    try:
        validate(record)
    except SchemaError as exc:
        print(f"error: schema validation failed for kind={record.get('kind')!r}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _write_record(record: dict, path: Path, *, force: bool) -> None:
    """Write record JSON to path. Fails if path exists and force=False."""
    if path.exists() and not force:
        print(
            f"error: {path} already exists; use --force-commit to overwrite",
            file=sys.stderr,
        )
        raise SystemExit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False, sort_keys=False),
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ── Main scan logic ───────────────────────────────────────────────────────────


def scan(
    project: str,
    repo_root: Path,
    *,
    depth: str = "shallow",
    commit: bool = False,
    force_commit: bool = False,
    memory_root: Path | None = None,
    quiet: bool = False,
) -> dict:
    """Run all detectors and return a dict of {kind: record} for the requested depth.

    If commit=True, writes files. If force_commit=True, overwrites existing files.
    If commit=False (dry-run), just returns the dict without touching the filesystem.
    """
    mem_root = memory_root or MEMORY_ROOT
    ts = now_iso()
    target_kinds = _DEPTH_KINDS.get(depth, SHALLOW_KINDS)

    # Always run all detectors (dev_env summary needs all of them)
    all_detectors = ["runtime", "tests", "deploy", "ci", "lint", "structure", "env_templates"]
    detector_results: dict[str, dict] = {}
    for det_kind in all_detectors:
        detector_fn = _KIND_DETECTOR_MAP[det_kind]
        try:
            detector_results[det_kind] = detector_fn(repo_root)
        except Exception as exc:
            if not quiet:
                print(f"warn: detector {det_kind} failed: {exc}", file=sys.stderr)
            detector_results[det_kind] = {"data": {}, "evidence": [{"source_url": f"file://{repo_root}", "trust": "low"}]}

    records: dict[str, dict] = {}

    for kind in target_kinds:
        if kind == "dev_env":
            record = _build_dev_env_summary(project, repo_root, detector_results, depth, ts)
        else:
            record = _build_kind_record(kind, project, ts, detector_results[kind])

        _validate_record(record)
        records[kind] = record

        if commit or force_commit:
            path_fn = _KIND_PATH_MAP[kind]
            path = path_fn(project, memory_root=mem_root)
            _write_record(record, path, force=force_commit)
            if not quiet:
                print(f"wrote: {path}", file=sys.stderr)

    return records


# ── CLI ───────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scan a project repository and write structured memory facts."
    )
    p.add_argument("--project", required=True, help="Project name (used as key in projects/<name>/)")
    p.add_argument("--repo", required=True, help="Absolute path to the project repository root")
    p.add_argument(
        "--depth",
        default="shallow",
        choices=["shallow", "medium", "deep"],
        help="Scan depth: shallow (dev_env only), medium (+6 granular), deep (+env_templates). Default: shallow",
    )
    p.add_argument(
        "--commit",
        action="store_true",
        help="Write files to projects/<name>/. Fails if files already exist.",
    )
    p.add_argument(
        "--force-commit",
        action="store_true",
        help="Write files; overwrite existing.",
    )
    p.add_argument(
        "--memory-dir",
        default=str(MEMORY_ROOT),
        help=f"Memory root directory (default: {MEMORY_ROOT})",
    )
    p.add_argument("--quiet", action="store_true", help="Suppress progress output")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo).expanduser().resolve()
    if not repo_root.is_dir():
        print(f"error: --repo {args.repo!r} is not a directory", file=sys.stderr)
        return 1

    memory_root = Path(args.memory_dir).expanduser().resolve()
    do_commit = args.commit or args.force_commit
    force = args.force_commit

    records = scan(
        args.project,
        repo_root,
        depth=args.depth,
        commit=do_commit,
        force_commit=force,
        memory_root=memory_root,
        quiet=args.quiet,
    )

    if not do_commit:
        # Dry-run: print JSON to stdout
        output = {
            "dry_run": True,
            "project": args.project,
            "repo": str(repo_root),
            "depth": args.depth,
            "files": {f"{kind}.json": record for kind, record in records.items()},
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        if not args.quiet:
            print(f"scan complete: {args.project} depth={args.depth} ({len(records)} files)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
