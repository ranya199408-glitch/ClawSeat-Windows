"""ClawSeat v3 acceptance executor (Phase 2).

Runs `brief.acceptance_criteria.{mechanical,reviewer,operator}` per spec §4.7.
Memory writes the acceptance criteria; planner invokes this executor after
all workflow steps finish.

Three routes:
- mechanical: physically run shell commands; capture stdout/stderr/exit
- reviewer:   dispatch to reviewer seat via dispatch_task.py (existing infra)
- operator:   write batched questions to operator-pending file; operator answers manually

See spec §4.7.4 (acceptance routing) + brief.schema.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = REPO_ROOT / "core" / "schemas" / "brief.schema.json"
# Ensure sibling lib modules importable when called as standalone
if str(REPO_ROOT / "core" / "lib") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "core" / "lib"))

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover — PyYAML is a hard dep
    yaml = None  # type: ignore


class AcceptanceError(RuntimeError):
    """Schema or invocation error. Distinct from acceptance FAIL (which is data)."""


@dataclass
class ItemResult:
    criterion: str
    result: str  # 'pass' | 'fail' | 'pending' | 'skipped'
    command: str | None = None
    exit_code: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    runtime_ms: int | None = None
    dispatch_receipt: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class RouteResult:
    route: str
    verdict: str  # 'PASS' | 'FAIL' | 'PENDING'
    items: list[ItemResult] = field(default_factory=list)


def _agents_root() -> Path:
    return Path(
        os.environ.get(
            "CLAWSEAT_REAL_HOME",
            os.environ.get("HOME", str(Path.home())),
        )
    ).expanduser() / ".agents"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stringify_datetimes(value):
    """Round 4 #D: recursively convert datetime/date to ISO strings.

    PyYAML safe_load auto-parses unquoted ISO timestamps to datetime objects;
    schemas declaring date-time format with type:string then reject them.
    Normalize before schema validation.
    """
    from datetime import date, datetime
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _stringify_datetimes(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify_datetimes(v) for v in value]
    return value


def _validate_brief_schema(brief: dict, brief_path: Path) -> None:
    """Post-retest #2 + Round 4 #D: validate brief against brief.schema.json.

    Schema enforces minItems:1 for seats_required and acceptance_criteria.mechanical,
    so empty acceptance can no longer vacuously PASS.

    Uses jsonschema when installed; falls back to lightweight required-field +
    minItems check sufficient for known v3 invariants.

    Round 4 #D: brief datetimes (created/deadline) are converted to ISO strings
    before validation to avoid PyYAML's auto-datetime coercion confusing the
    schema's string format declaration.
    """
    brief = _stringify_datetimes(brief)
    try:
        import jsonschema  # type: ignore
    except ImportError:
        # Lightweight fallback: enforce the two minItems we care about.
        seats = brief.get("seats_required")
        if not isinstance(seats, list) or not seats:
            raise AcceptanceError(
                f"{brief_path}: brief.seats_required must have minItems 1"
            )
        ac = brief.get("acceptance_criteria") or {}
        mech = ac.get("mechanical")
        if not isinstance(mech, list) or not mech:
            raise AcceptanceError(
                f"{brief_path}: brief.acceptance_criteria.mechanical must have minItems 1"
            )
        return

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(brief, schema)
    except jsonschema.ValidationError as exc:
        raise AcceptanceError(
            f"{brief_path}: brief schema violation — {exc.message} (at {'.'.join(str(p) for p in exc.absolute_path)})"
        )


def _load_brief(brief_path: Path) -> dict:
    if yaml is None:
        raise AcceptanceError("PyYAML required")
    text = brief_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise AcceptanceError(f"{brief_path}: missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        end = text.find("\n---", 4)
    if end == -1:
        raise AcceptanceError(f"{brief_path}: unterminated frontmatter")
    data = yaml.safe_load(text[4:end])
    if not isinstance(data, dict):
        raise AcceptanceError(f"{brief_path}: frontmatter is not a mapping")
    return data


def _criterion_command_and_text(criterion: Any) -> tuple[str, str]:
    """Normalize a criterion entry to (display_text, shell_command)."""
    if isinstance(criterion, str):
        return criterion, criterion
    if isinstance(criterion, dict):
        cmd = criterion.get("command") or criterion.get("criterion") or ""
        text = criterion.get("description") or cmd
        return str(text), str(cmd)
    raise AcceptanceError(f"unrecognized criterion shape: {criterion!r}")


def _criterion_route(criterion: Any) -> str:
    """Post-retest #6: per-criterion route override.

    Default for items inside mechanical[] is 'mechanical'. If a dict criterion
    declares route: reviewer/operator, it diverts there even when nested in
    the mechanical section.
    """
    if isinstance(criterion, dict):
        route = str(criterion.get("route") or "").strip()
        if route in ("mechanical", "reviewer", "operator"):
            return route
    return "mechanical"


def _split_by_route(brief: dict) -> tuple[list, list, list]:
    """Round 4 #A: split criteria by per-item route override.

    For each section in brief.acceptance_criteria (mechanical/reviewer/operator),
    inspect each item's `route` field. Items with explicit route override are
    moved to the target section. Returns (mech_items, reviewer_items, operator_items).
    """
    acceptance = brief.get("acceptance_criteria") or {}
    base_mech = acceptance.get("mechanical") or []
    base_rev = list(acceptance.get("reviewer") or [])
    base_op = list(acceptance.get("operator") or [])

    final_mech: list = []
    for item in base_mech:
        route = _criterion_route(item)
        if route == "reviewer":
            base_rev.append(item)
        elif route == "operator":
            base_op.append(item)
        else:
            final_mech.append(item)
    return final_mech, base_rev, base_op


def run_mechanical(
    brief: dict,
    acceptance_dir: Path,
    task_id: str,
    cwd: Path | None = None,
    env_overrides: dict[str, str] | None = None,
    pre_split_mech: list | None = None,
) -> RouteResult:
    """Run each mechanical criterion. Returns aggregate verdict.

    Captures stdout + stderr to per-criterion files under acceptance_dir.

    Round 4 #A: caller normally passes `pre_split_mech` (already filtered to
    items truly destined for mechanical execution); items with route override
    have been re-routed by the caller. Backwards-compatible: when None, the
    function recomputes the split internally.
    """
    if pre_split_mech is None:
        pre_split_mech, _, _ = _split_by_route(brief)
    mech = pre_split_mech
    result = RouteResult(route="mechanical", verdict="PASS")

    # Post-retest #2: empty mechanical (after route splitting) is FAIL if the
    # ORIGINAL brief had no mechanical work at all. If the original had work
    # but route overrides moved it all to other routes, also FAIL — at least
    # one mechanical item must remain (schema minItems:1).
    if not mech:
        original = (brief.get("acceptance_criteria") or {}).get("mechanical") or []
        if not original:
            result.verdict = "FAIL"
            return result
        # All original items were route-shifted; still must record FAIL
        # because spec demands at least one truly mechanical criterion.
        result.verdict = "FAIL"
        result.items.append(
            ItemResult(
                criterion="<no items remain in mechanical after route overrides>",
                result="fail",
                command="route_split",
            )
        )
        return result

    acceptance_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)

    any_fail = False
    for idx, item in enumerate(mech):
        text, cmd = _criterion_command_and_text(item)
        if not cmd:
            result.items.append(ItemResult(criterion=text, result="skipped"))
            continue
        stdout_p = acceptance_dir / f"{task_id}__mech__{idx:02d}.stdout"
        stderr_p = acceptance_dir / f"{task_id}__mech__{idx:02d}.stderr"
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(cwd) if cwd else None,
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
            )
            runtime_ms = int((time.monotonic() - start) * 1000)
            stdout_p.write_text(proc.stdout, encoding="utf-8")
            stderr_p.write_text(proc.stderr, encoding="utf-8")
            verdict = "pass" if proc.returncode == 0 else "fail"
            if verdict == "fail":
                any_fail = True
            result.items.append(
                ItemResult(
                    criterion=text,
                    result=verdict,
                    command=cmd,
                    exit_code=proc.returncode,
                    stdout_path=str(stdout_p),
                    stderr_path=str(stderr_p),
                    runtime_ms=runtime_ms,
                )
            )
        except subprocess.TimeoutExpired as exc:
            runtime_ms = int((time.monotonic() - start) * 1000)
            stdout_p.write_text(exc.stdout or "", encoding="utf-8")
            stderr_p.write_text(
                (exc.stderr or "") + f"\n[acceptance_executor] timeout after {runtime_ms}ms",
                encoding="utf-8",
            )
            any_fail = True
            result.items.append(
                ItemResult(
                    criterion=text,
                    result="fail",
                    command=cmd,
                    exit_code=-1,
                    stdout_path=str(stdout_p),
                    stderr_path=str(stderr_p),
                    runtime_ms=runtime_ms,
                )
            )

    result.verdict = "FAIL" if any_fail else "PASS"
    return result


def route_reviewer(
    brief: dict,
    project: str,
    team: str,
    task_id: str,
    acceptance_dir: Path,
    reviewer_seat: str | None = None,
    dispatch_fn=None,
    pre_split_items: list | None = None,
) -> RouteResult:
    """Route reviewer items via dispatch_task.py. PENDING until reviewer relays.

    dispatch_fn is injected for testing; in production it shells out to
    `dispatch_task.py`. We don't fail if reviewer is offline — we record
    PENDING and let planner watch DELIVERY.md as in existing 7-step loop.

    Round 4 #A: caller supplies `pre_split_items` (reviewer items plus any
    mechanical items with route=reviewer override). Backwards-compatible:
    None falls back to bare brief.reviewer list.
    """
    items = (
        pre_split_items
        if pre_split_items is not None
        else (brief.get("acceptance_criteria") or {}).get("reviewer") or []
    )
    result = RouteResult(route="reviewer", verdict="PASS")  # vacuous PASS if empty

    if not items:
        return result

    result.verdict = "PENDING"
    acceptance_dir.mkdir(parents=True, exist_ok=True)

    # Materialize a single dispatch packet listing all reviewer items.
    packet_path = acceptance_dir / f"{task_id}__reviewer.dispatch.json"
    packet = {
        "task_id": task_id,
        "project": project,
        "team": team,
        "reviewer_seat": reviewer_seat or f"{team}-reviewer",
        "items": [_criterion_command_and_text(c)[0] for c in items],
        "ts": _utc_now(),
    }
    packet_path.write_text(json.dumps(packet, indent=2, ensure_ascii=False), encoding="utf-8")

    if dispatch_fn is not None:
        try:
            dispatch_receipt = dispatch_fn(packet)
        except Exception as exc:  # noqa: BLE001
            dispatch_receipt = f"dispatch error: {exc}"
    else:
        dispatch_receipt = str(packet_path)  # placeholder; planner uses existing dispatch infra

    for c in items:
        text, _ = _criterion_command_and_text(c)
        result.items.append(
            ItemResult(
                criterion=text,
                result="pending",
                dispatch_receipt=dispatch_receipt,
            )
        )
    return result


def route_operator(
    brief: dict,
    project: str,
    team: str,
    task_id: str,
    acceptance_dir: Path,
    pre_split_items: list | None = None,
) -> RouteResult:
    """Batch operator items into a pending-answer file.

    Round 4 #A: pre_split_items includes operator-routed items from any
    section (including mechanical with route=operator override).
    """
    items = (
        pre_split_items
        if pre_split_items is not None
        else (brief.get("acceptance_criteria") or {}).get("operator") or []
    )
    result = RouteResult(route="operator", verdict="PASS")  # vacuous PASS

    if not items:
        return result

    result.verdict = "PENDING"
    acceptance_dir.mkdir(parents=True, exist_ok=True)
    pending_path = acceptance_dir / f"{task_id}__operator.pending.json"

    questions = []
    for idx, c in enumerate(items):
        text, _ = _criterion_command_and_text(c)
        questions.append({"id": f"q{idx:02d}", "criterion": text, "answer": None, "answered_ts": None})

    pending_path.write_text(
        json.dumps({"task_id": task_id, "project": project, "team": team, "ts": _utc_now(), "questions": questions}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    for q in questions:
        result.items.append(ItemResult(criterion=q["criterion"], result="pending"))

    return result


def _validate_brief_matches_cli(brief: dict, project: str, team: str, task_id: str) -> None:
    """Post-review Phase 2 fix #A: refuse to run when brief frontmatter
    disagrees with CLI args. Prevents wrong task/project being marked accepted."""
    mismatches = []
    for field, expected in (("task_id", task_id), ("project", project), ("team", team)):
        actual = brief.get(field)
        if actual is None:
            mismatches.append(f"brief missing {field}")
        elif str(actual) != str(expected):
            mismatches.append(f"brief.{field}={actual!r} vs CLI {field}={expected!r}")
    if mismatches:
        raise AcceptanceError("brief vs CLI mismatch: " + "; ".join(mismatches))


def run_acceptance(
    project: str,
    team: str,
    task_id: str,
    brief_path: Path | None = None,
    reviewer_seat: str | None = None,
    dispatch_fn=None,
    cwd: Path | None = None,
    profile_path: Path | None = None,
) -> dict[str, RouteResult]:
    """Top-level entry: run all three routes, write receipts, return dict.

    Caller (typically planner via agent_admin acceptance run) uses the
    aggregate verdict to decide next step.
    """
    agents_root = _agents_root()
    if brief_path is None:
        brief_path = agents_root / "tasks" / project / team / "brief" / f"{task_id}.md"
    if not brief_path.exists():
        raise AcceptanceError(f"brief not found: {brief_path}")
    brief = _load_brief(brief_path)

    # Phase 2 fix #A: brief frontmatter must agree with CLI args
    _validate_brief_matches_cli(brief, project, team, task_id)

    # Post-retest #2: brief must conform to brief.schema.json
    _validate_brief_schema(brief, brief_path)

    acceptance_dir = agents_root / "tasks" / project / team / "acceptance"

    # Default reviewer dispatch: invoke real dispatch_task.py subprocess (fix #C).
    # Inject None or a fake to opt out (used in tests).
    if dispatch_fn is None:
        dispatch_fn = lambda packet: _default_reviewer_dispatch(  # noqa: E731
            packet, profile_path=profile_path, agents_root=agents_root, project=project
        )

    # Round 4 #A: split criteria once by route, pass to each route helper
    final_mech, final_rev, final_op = _split_by_route(brief)
    results = {
        "mechanical": run_mechanical(
            brief, acceptance_dir, task_id, cwd=cwd, pre_split_mech=final_mech
        ),
        "reviewer": route_reviewer(
            brief, project, team, task_id, acceptance_dir,
            reviewer_seat=reviewer_seat, dispatch_fn=dispatch_fn,
            pre_split_items=final_rev,
        ),
        "operator": route_operator(
            brief, project, team, task_id, acceptance_dir,
            pre_split_items=final_op,
        ),
    }

    # Post-retest #3: wire fuzz_required into acceptance. When the brief
    # declares fuzz_required=true, an absent/failed fuzz run downgrades the
    # mechanical verdict to FAIL (spec §4.7.3).
    fuzz_outcome = _maybe_run_fuzz(brief, acceptance_dir, task_id)
    if fuzz_outcome is not None:
        # Append a synthetic mechanical item that captures fuzz result
        mech = results["mechanical"]
        mech.items.append(fuzz_outcome)
        if fuzz_outcome.result != "pass":
            mech.verdict = "FAIL"

    # Phase 2 fix #B: consolidated __mechanical.log per spec §4.7.1
    _write_mechanical_consolidated_log(
        acceptance_dir, task_id, results["mechanical"]
    )

    # Persist mechanical receipt
    mech_receipt = acceptance_dir / f"{task_id}__mechanical.json"
    _write_receipt(mech_receipt, project, team, task_id, results["mechanical"])

    # Persist reviewer/operator state too (verdict=PENDING until they answer)
    rev_receipt = acceptance_dir / f"{task_id}__reviewer.json"
    _write_receipt(rev_receipt, project, team, task_id, results["reviewer"])

    op_receipt = acceptance_dir / f"{task_id}__operator.json"
    _write_receipt(op_receipt, project, team, task_id, results["operator"])

    return results


def _maybe_run_fuzz(
    brief: dict, acceptance_dir: Path, task_id: str
) -> ItemResult | None:
    """Post-retest #3: invoke fuzz_harness when brief.fuzz_required=true.

    Returns an ItemResult capturing the fuzz outcome (to append to mechanical),
    or None if fuzz_required is false / absent.

    FAIL conditions:
    - fuzz_required=true but fuzz_spec missing/empty → FAIL
    - fuzz harness reports any failure → FAIL
    - fuzz harness raises → FAIL
    """
    if not brief.get("fuzz_required"):
        return None

    spec = brief.get("fuzz_spec")
    descriptor = "fuzz (required by brief.fuzz_required)"
    if not spec:
        return ItemResult(
            criterion=descriptor,
            result="fail",
            command="fuzz_harness",
            exit_code=-1,
            runtime_ms=0,
        )

    # spec may be either a single spec dict OR list of spec dicts; normalize
    if isinstance(spec, dict):
        specs = [spec]
    elif isinstance(spec, list):
        specs = list(spec)
    else:
        return ItemResult(
            criterion=descriptor + f" (invalid spec type: {type(spec).__name__})",
            result="fail",
            command="fuzz_harness",
        )

    # Import lazily to avoid circular if fuzz_harness imports from executor.
    from fuzz_harness import FuzzError, run_fuzz

    acceptance_dir.mkdir(parents=True, exist_ok=True)
    any_failure = False
    aggregate_runtime = 0
    aggregate_cases = 0
    aggregate_failures = 0

    for s in specs:
        s_dict = dict(s) if isinstance(s, dict) else {}
        target_command = s_dict.pop("target_command", None)
        iterations = int(s_dict.pop("iterations", 100))
        seed = s_dict.pop("seed", None)

        # Round 4 #C: fuzz_required must be exercised against a real target.
        # No more permissive JSON-noop fallback — missing target_command is FAIL.
        if not target_command:
            return ItemResult(
                criterion=descriptor + " (spec missing target_command — won't run)",
                result="fail",
                command="fuzz_harness",
            )

        try:
            r = run_fuzz(
                s_dict,
                target_command=target_command,
                iterations=iterations,
                seed=seed,
                out_dir=acceptance_dir / "fuzz",
            )
            aggregate_cases += r.cases_run
            aggregate_runtime += r.elapsed_ms
            if r.failures:
                any_failure = True
                aggregate_failures += len(r.failures)
        except FuzzError as exc:
            return ItemResult(
                criterion=descriptor + f" (spec error: {exc})",
                result="fail",
                command="fuzz_harness",
            )

    return ItemResult(
        criterion=(
            f"{descriptor}: {aggregate_cases} cases, {aggregate_failures} failures"
        ),
        result="fail" if any_failure else "pass",
        command="fuzz_harness",
        runtime_ms=aggregate_runtime,
    )


def _default_reviewer_dispatch(
    packet: dict,
    *,
    profile_path: Path | None,
    agents_root: Path,
    project: str,
) -> str:
    """Phase 2 fix #C: actually invoke dispatch_task.py subprocess.

    Returns a string describing the outcome (success → 'dispatched seq=…';
    profile missing → 'skipped: profile not found'; subprocess fail → error
    string). Acceptance receipt records this in dispatch_receipt field.
    """
    if profile_path is None:
        profile_path = agents_root / "profiles" / f"{project}-profile-dynamic.toml"
    if not Path(profile_path).exists():
        return f"skipped: profile not found at {profile_path}"

    repo_root = Path(__file__).resolve().parents[2]
    dispatch_script = repo_root / "core" / "skills" / "gstack-harness" / "scripts" / "dispatch_task.py"
    if not dispatch_script.exists():
        return f"skipped: dispatch_task.py not found at {dispatch_script}"

    items = packet.get("items") or []
    if not items:
        return "skipped: no reviewer items"

    objective = "Acceptance review batch: " + "; ".join(items[:10])
    if len(items) > 10:
        objective += f" (+ {len(items) - 10} more)"

    task_id = str(packet["task_id"])
    reviewer_seat = str(packet["reviewer_seat"])
    review_task_id = f"{task_id}__accept_review"

    cmd = [
        sys.executable,
        str(dispatch_script),
        "--profile", str(profile_path),
        "--source", "memory",        # executor invokes on behalf of memory's acceptance
        "--target", reviewer_seat,
        "--task-id", review_task_id,
        "--title", f"acceptance review for {task_id}",
        "--objective", objective,
        "--test-policy", "N/A",
        "--reply-to", "memory",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "error: dispatch_task.py timeout 60s"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()[-1] if (proc.stderr or proc.stdout) else f"exit {proc.returncode}"
        return f"error: dispatch_task.py exit {proc.returncode}: {err[:200]}"
    return f"dispatched: task_id={review_task_id} target={reviewer_seat}"


def _write_mechanical_consolidated_log(
    acceptance_dir: Path, task_id: str, result: RouteResult
) -> None:
    """Phase 2 fix #B: write consolidated __mechanical.log per spec §4.7.1."""
    acceptance_dir.mkdir(parents=True, exist_ok=True)
    log_path = acceptance_dir / f"{task_id}__mechanical.log"
    lines: list[str] = [
        f"# Mechanical acceptance log for task_id={task_id}",
        f"# Verdict: {result.verdict}",
        f"# Generated: {_utc_now()}",
        "",
    ]
    for idx, item in enumerate(result.items):
        lines.append("=" * 72)
        lines.append(f"Criterion #{idx}: {item.criterion}")
        lines.append(f"Result: {item.result}")
        if item.command:
            lines.append(f"Command: {item.command}")
        if item.exit_code is not None:
            lines.append(f"Exit code: {item.exit_code}")
        if item.runtime_ms is not None:
            lines.append(f"Runtime: {item.runtime_ms} ms")
        if item.stdout_path:
            stdout_text = ""
            try:
                stdout_text = Path(item.stdout_path).read_text(encoding="utf-8")
            except OSError:
                pass
            lines.append("--- stdout ---")
            lines.append(stdout_text.rstrip())
        if item.stderr_path:
            stderr_text = ""
            try:
                stderr_text = Path(item.stderr_path).read_text(encoding="utf-8")
            except OSError:
                pass
            lines.append("--- stderr ---")
            lines.append(stderr_text.rstrip())
        lines.append("")
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_receipt(path: Path, project: str, team: str, task_id: str, result: RouteResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "total": len(result.items),
        "pass": sum(1 for i in result.items if i.result == "pass"),
        "fail": sum(1 for i in result.items if i.result == "fail"),
        "pending": sum(1 for i in result.items if i.result == "pending"),
    }
    payload = {
        "task_id": task_id,
        "project": project,
        "team": team,
        "ts": _utc_now(),
        "route": result.route,
        "verdict": result.verdict,
        "items": [i.to_dict() for i in result.items],
        "summary": summary,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def aggregate_verdict(results: dict[str, RouteResult]) -> str:
    """PASS only when mechanical PASS and reviewer/operator are PASS or PENDING (empty).

    FAIL if mechanical FAIL. PENDING if mechanical PASS but reviewer/operator
    has work outstanding.
    """
    mech = results.get("mechanical")
    if mech is None or mech.verdict == "FAIL":
        return "FAIL"
    if any(r.verdict == "PENDING" for r in results.values()):
        return "PENDING"
    return "PASS"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="ClawSeat v3 acceptance executor (mechanical/reviewer/operator routes)."
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--team", required=True)
    parser.add_argument("--task-id", required=True, dest="task_id")
    parser.add_argument("--brief-path", default=None, dest="brief_path",
                        help="Explicit brief path (default: tasks/<p>/<t>/brief/<task_id>.md)")
    parser.add_argument("--reviewer-seat", default=None, dest="reviewer_seat")
    parser.add_argument("--cwd", default=None, help="Working dir for mechanical commands")
    parser.add_argument("--profile", default=None, dest="profile",
                        help="Optional profile path for reviewer dispatch (default: ~/.agents/profiles/<project>-profile-dynamic.toml)")
    args = parser.parse_args(argv)

    try:
        results = run_acceptance(
            project=args.project,
            team=args.team,
            task_id=args.task_id,
            brief_path=Path(args.brief_path) if args.brief_path else None,
            reviewer_seat=args.reviewer_seat,
            cwd=Path(args.cwd) if args.cwd else None,
            profile_path=Path(args.profile) if args.profile else None,
        )
    except AcceptanceError as exc:
        print(f"acceptance schema error: {exc}", file=sys.stderr)
        return 2

    verdict = aggregate_verdict(results)
    for route, r in results.items():
        passed = sum(1 for i in r.items if i.result == "pass")
        failed = sum(1 for i in r.items if i.result == "fail")
        pending = sum(1 for i in r.items if i.result == "pending")
        print(f"{route}: {r.verdict} (pass={passed} fail={failed} pending={pending})")
    print(f"aggregate: {verdict}")

    # Exit code mapping per planner-brief-parsing-contract.md §4
    if verdict == "FAIL":
        return 1
    return 0  # PASS or PENDING


if __name__ == "__main__":
    raise SystemExit(main())
