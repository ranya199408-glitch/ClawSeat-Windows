#!/usr/bin/env python3
# DEPRECATED (2026-04-22): transitional dynamic-roster compatibility shim.
# Keep until every live profile has `[dynamic_roster].enabled = true` and the
# router-level migration cleanup can delete the last legacy/static caller.
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Ensure repo root is on sys.path so core.lib.state is importable.
_REPO_ROOT_DYN = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT_DYN) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_DYN))

from core.lib.real_home import real_user_home


def _resolve_gstack_skills_root() -> str:
    env = os.environ.get("GSTACK_SKILLS_ROOT", "")
    if env:
        expanded = Path(env).expanduser()
        if expanded.is_absolute():
            return str(expanded)
    return str(real_user_home() / ".gstack" / "repos" / "gstack" / ".agents" / "skills")


_GSTACK_SKILLS_ROOT = _resolve_gstack_skills_root()

INTENT_MAP: dict[str, dict[str, str]] = {
    "eng-review": {
        "trigger": "Review the architecture and lock in the plan",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-plan-eng-review/SKILL.md",
        "description": "engineering plan review (architecture / data flow / test coverage / perf)",
    },
    "ceo-review": {
        "trigger": "Think bigger and expand scope if it creates a better product",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-plan-ceo-review/SKILL.md",
        "description": "CEO/founder-mode strategy review (scope expand / hold / reduce)",
    },
    "design-review": {
        "trigger": "Review the design plan and design critique",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-plan-design-review/SKILL.md",
        "description": "designer's-eye plan review (UX / visual / component; plan-mode)",
    },
    "devex-review": {
        "trigger": "DX review and developer experience audit (Addy Osmani framework)",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-plan-devex-review/SKILL.md",
        "description": "developer experience audit (zero friction / learn by doing / fight uncertainty)",
    },
    "ship": {
        "trigger": "Ship it and create a PR (run tests, review diff, bump VERSION, update CHANGELOG)",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-ship/SKILL.md",
        "description": "ship workflow (test → diff → version → commit → push → PR)",
    },
    "land": {
        "trigger": "Land the PR and deploy — merge, wait for CI and deploy, verify production",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-land-and-deploy/SKILL.md",
        "description": "merge + canary + production verification",
    },
    "investigate": {
        "trigger": "Investigate root cause — debug this, why is this broken, root cause analysis",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-investigate/SKILL.md",
        "description": "bug RCA (investigate → analyze → hypothesize → implement)",
    },
    "freeze": {
        "trigger": "Freeze and restrict edits to this directory",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-freeze/SKILL.md",
        "description": "restrict Edit/Write to one module for the session",
    },
    "unfreeze": {
        "trigger": "Unfreeze and remove the edit restriction",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-unfreeze/SKILL.md",
        "description": "clear the /freeze boundary, allow all-directory edits again",
    },
    "code-review": {
        "trigger": "Code review — pre-landing PR review, check the diff for SQL safety, LLM trust, conditional side effects, structural issues",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-review/SKILL.md",
        "description": "pre-landing PR review (NOT plan-review; for final diff check)",
    },
    "qa-test": {
        "trigger": "QA — systematically test this web app and fix bugs found (test → fix → verify loop)",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-qa/SKILL.md",
        "description": "full QA test-fix-verify loop with before/after health scores",
    },
    "qa-only": {
        "trigger": "QA report only — just report bugs, don't fix anything",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-qa-only/SKILL.md",
        "description": "report-only QA (no source code edits, only a structured report)",
    },
    "design-critique": {
        "trigger": "Audit the design — visual QA, check if it looks good, design polish (post-implementation)",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-design-review/SKILL.md",
        "description": "post-implementation visual audit (iteratively fixes visual issues)",
    },
    "design-html": {
        "trigger": "Finalize this design and turn it into production HTML/CSS",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-design-html/SKILL.md",
        "description": "design → production HTML/CSS via Pretext patterns",
    },
    "design-shotgun": {
        "trigger": "Design shotgun — generate multiple AI design variants and compare",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-design-shotgun/SKILL.md",
        "description": "multi-variant design exploration with comparison board",
    },
    "office-hours": {
        "trigger": "Office hours brainstorm — help me think through this, is this worth building",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-office-hours/SKILL.md",
        "description": "YC office-hours brainstorm (6 forcing questions / design doc)",
    },
    "checkpoint": {
        "trigger": "Checkpoint — save progress and where was I",
        "skill_md": f"{_GSTACK_SKILLS_ROOT}/gstack-checkpoint/SKILL.md",
        "description": "save/resume working state across sessions",
    },
}


def apply_intent(
    intent: str | None,
    objective: str,
    skill_refs: list[str] | None,
) -> tuple[str, list[str]]:
    if intent is None:
        return objective, (skill_refs or [])
    if intent not in INTENT_MAP:
        valid = ", ".join(sorted(INTENT_MAP.keys()))
        raise ValueError(f"unknown --intent {intent!r}; valid intents: {valid}")
    spec = INTENT_MAP[intent]
    trigger = spec["trigger"]
    skill_md = spec["skill_md"]
    if trigger.lower() not in objective.lower():
        new_objective = f"**{trigger}** — {objective.strip()}"
    else:
        new_objective = objective
    refs = list(skill_refs or [])
    if skill_md not in refs:
        refs.append(skill_md)
    return new_objective, refs

from dynamic_common import (
    add_notify_args,
    append_status_note,
    assert_target_not_memory,
    build_notify_message,
    load_profile,
    notify,
    preferred_planner_seat,
    normalize_role,
    require_success,
    resolve_notify,
    utc_now_iso,
    write_json,
    write_todo,
    upsert_tasks_row,
)


def _write_dispatch_to_ledger(
    *,
    task_id: str,
    project: str,
    source: str,
    target: str,
    role_hint: str | None,
    title: str,
    correlation_id: str | None = None,
) -> None:
    """Write task + task.dispatched event to state.db. Defensive: never fails dispatch."""
    try:
        from datetime import datetime, timezone as _tz
        from core.lib.state import open_db, record_task_dispatched, record_event, Task
        task = Task(
            id=task_id,
            project=project,
            source=source,
            target=target,
            role_hint=role_hint,
            status="dispatched",
            title=title,
            correlation_id=correlation_id,
            opened_at=datetime.now(_tz.utc).isoformat(timespec="seconds"),
        )
        with open_db() as conn:
            record_task_dispatched(conn, task)
            record_event(conn, "task.dispatched", project,
                         task_id=task_id, source=source, target=target)
    except Exception as exc:
        print(f"warn: state.db unavailable, skipping ledger write: {exc}", file=sys.stderr)


def _git_main_tip(repo_root: Path | str | None) -> str | None:
    if not repo_root:
        return None
    root = Path(repo_root)
    if not root.exists():
        return None
    for ref in ("clawseat/main", "origin/main"):
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "rev-parse", ref],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception:
            continue
        sha = result.stdout.strip()
        if sha:
            return sha
    return None


def _git_head_tip(repo_root: Path | str | None) -> str | None:
    if not repo_root:
        return None
    root = Path(repo_root)
    if not root.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    sha = result.stdout.strip()
    return sha or None


def _git_merge_base_is_ancestor(repo_root: Path | str | None, reported_commit: str) -> bool | None:
    if not repo_root:
        return None
    root = Path(repo_root)
    if not root.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", reported_commit, "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


def _populate_lineage_receipt_fields(
    *,
    repo_root: Path | str | None,
    expected_base_sha: str | None,
    source_role: str,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "builder_commit": None,
        "memory_commit": None,
        "head_contains_commit": False,
        "lineage_status": "unknown",
    }
    builder_commit = expected_base_sha.strip() if isinstance(expected_base_sha, str) and expected_base_sha.strip() else None
    if builder_commit:
        fields["builder_commit"] = builder_commit
        contains = _git_merge_base_is_ancestor(repo_root, builder_commit)
        if contains is True:
            fields["head_contains_commit"] = True
            fields["lineage_status"] = "in-lineage"
        elif contains is False:
            fields["head_contains_commit"] = False
            fields["lineage_status"] = "divergent"
    if normalize_role(source_role) == "memory":
        fields["memory_commit"] = _git_head_tip(repo_root)
    return fields


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatch a task to a dynamic-roster seat.")
    parser.add_argument("--profile", required=True, help="Path to the dynamic profile TOML.")
    parser.add_argument("--source", help="Seat dispatching the task. Defaults to the resolved planner seat.")
    _target_group = parser.add_mutually_exclusive_group(required=True)
    _target_group.add_argument("--target", help="Target seat (explicit seat id).")
    _target_group.add_argument(
        "--target-role",
        metavar="ROLE",
        help="Pick least-busy live seat with this role from state.db.",
    )
    parser.add_argument("--task-id", required=True, help="Task id.")
    parser.add_argument("--title", required=True, help="Task title.")
    parser.add_argument("--objective", required=True, help="Objective/body text for the TODO.")
    parser.add_argument(
        "--test-policy",
        required=True,
        choices=["UPDATE", "FREEZE", "EXTEND", "N/A"],
        help=(
            "UPDATE: tests must follow code changes; "
            "FREEZE: do not touch tests; "
            "EXTEND: add new tests only; "
            "N/A: doc/config only, no testable code"
        ),
    )
    parser.add_argument("--reply-to", help="Seat that should receive completion back from the target.")
    parser.add_argument("--notes", default="dispatched via dynamic-roster harness", help="TASKS.md note.")
    parser.add_argument("--status-note", help="Optional STATUS.md note.")
    parser.add_argument(
        "--skill-refs",
        nargs="*",
        metavar="SKILL_REF",
        default=None,
        help="Optional skill documentation pointers to include in the dispatched TODO.md.",
    )
    parser.add_argument(
        "--intent",
        choices=sorted(INTENT_MAP.keys()),
        default=None,
        help=(
            "High-level user-intent key that auto-injects the canonical gstack "
            "skill trigger phrase into --objective AND appends the skill's "
            "SKILL.md path to --skill-refs. "
            "Valid keys: " + ", ".join(sorted(INTENT_MAP.keys())) + "."
        ),
    )
    add_notify_args(parser)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    do_notify = resolve_notify(args)
    role_hint: str | None = getattr(args, "target_role", None)

    # Resolve --target-role via state.db (requires project_name from profile).
    profile = None
    if role_hint:
        profile = load_profile(args.profile)
        try:
            from core.lib.state import open_db, pick_least_busy_seat
            with open_db() as conn:
                picked = pick_least_busy_seat(conn, profile.project_name, role_hint)
        except Exception as exc:
            print(f"warn: state.db unavailable for role resolution: {exc}", file=sys.stderr)
            picked = None
        if picked is None:
            print(
                f"seat_needed: no live seat with role={role_hint!r} in "
                f"project={profile.project_name!r}. "
                "Launch one or specify --target explicitly.",
                file=sys.stderr,
            )
            return 3
        args.target = picked.seat_id
        print(f"target-role resolved: {role_hint} -> {args.target}", file=sys.stderr)

    # T9: block dispatch to memory before profile load — memory is a
    # synchronous oracle, never a task worker. See _common.py guard docstring.
    assert_target_not_memory(args.target, "dispatch_task_dynamic.py")
    if profile is None:
        profile = load_profile(args.profile)
    source = args.source or preferred_planner_seat(profile)
    source_role = normalize_role(profile.seat_roles.get(source, ""))
    todo_path = profile.todo_path(args.target)
    reply_to = args.reply_to or source
    expected_base_sha = _git_main_tip(getattr(profile, "repo_root", None))
    effective_objective, effective_skill_refs = apply_intent(
        args.intent,
        args.objective,
        args.skill_refs,
    )
    if effective_skill_refs:
        skill_refs_section = "\n\n# Skill Refs\n" + "\n".join(f"- {r}" for r in effective_skill_refs)
        effective_objective = effective_objective.rstrip() + skill_refs_section
    write_todo(
        todo_path,
        task_id=args.task_id,
        project=profile.project_name,
        owner=args.target,
        status="pending",
        title=args.title,
        objective=effective_objective,
        source=source,
        reply_to=reply_to,
        test_policy=args.test_policy,
    )
    upsert_tasks_row(
        profile.tasks_doc,
        task_id=args.task_id,
        title=args.title,
        owner=args.target,
        status="pending",
        notes=args.notes,
    )
    append_status_note(
        profile.status_doc,
        args.status_note or f"{source} dispatched {args.task_id} to {args.target} test_policy={args.test_policy}",
    )
    receipt = {
        "project": profile.project_name,
        "kind": "dispatch",
        "task_id": args.task_id,
        "source": source,
        "target": args.target,
        "title": args.title,
        "test_policy": args.test_policy,
        "todo_path": str(todo_path),
        "reply_to": reply_to,
        "assigned_at": utc_now_iso(),
        "notified_at": None,
        "notify_message": None,
    }
    if expected_base_sha:
        receipt["expected_base_sha"] = expected_base_sha
    receipt.update(
        _populate_lineage_receipt_fields(
            repo_root=getattr(profile, "repo_root", None),
            expected_base_sha=expected_base_sha,
            source_role=source_role,
        )
    )
    if do_notify:
        message = build_notify_message(
            profile.project_name,
            args.target,
            todo_path,
            args.task_id,
            source=source,
            reply_to=reply_to,
        )
        result = notify(profile, args.target, message)
        require_success(result, "dispatch notify")
        receipt["notified_at"] = utc_now_iso()
        receipt["notify_message"] = message
    receipt_path = profile.handoff_path(args.task_id, source, args.target)
    write_json(receipt_path, receipt)
    _write_dispatch_to_ledger(
        task_id=args.task_id,
        project=profile.project_name,
        source=source,
        target=args.target,
        role_hint=role_hint,
        title=args.title,
    )
    print(f"dispatched {args.task_id} -> {args.target}")
    print(f"todo: {todo_path}")
    print(f"receipt: {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
