"""Bootstrap completeness checker (C7).

At bootstrap / reconfigure time, verify the project has the structural
artefacts that runtime seats will expect. Failures here show up far
later — a project missing ``PLANNER_BRIEF.md`` lets planner boot,
accept a task, then silently skip context reads. A preflight is always
cheaper than a mid-task surprise.

Checks:

  1. ``tasks_root`` exists and is writable.
  2. Canonical docs: PROJECT.md, TASKS.md, STATUS.md — exist or the
     directory that should contain them is writable so the missing
     docs can be synthesized at bootstrap end.
  3. ``send_script`` file exists and is executable.
  4. If a ``planner`` seat is declared: the ``[patrol].planner_brief_path``
     file (or its default ``<tasks_root>/planner/PLANNER_BRIEF.md``)
     is present, or at least its parent dir is writable.
  5. ``PROJECT_BINDING.toml`` (C2) is present — if not, a *warning*,
     not a failure, because the install flow might be at pre-binding
     stage; the koder frontstage skill captures the group id later.
  6. A few informational signals (seat_roles coverage, heartbeat
     ownership) get logged as ``info`` items so operators see the
     shape of the project at a glance.

The caller chooses whether to treat warnings as failures by consuming
``.has_errors`` (hard failures) vs ``.has_warnings``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CompletenessItem:
    check: str
    severity: str        # "ok" | "warning" | "error" | "info"
    detail: str
    fix: str = ""


@dataclass
class CompletenessReport:
    project: str
    items: list[CompletenessItem] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.items)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warning" for i in self.items)

    def render(self) -> str:
        lines = [f"bootstrap-completeness project={self.project}"]
        # Stable render order: errors first, then warnings, then ok, then info.
        order = {"error": 0, "warning": 1, "ok": 2, "info": 3}
        for item in sorted(self.items, key=lambda i: (order.get(i.severity, 9), i.check)):
            label = {
                "error": "FAIL",
                "warning": "WARN",
                "ok": "OK",
                "info": "INFO",
            }.get(item.severity, "?")
            lines.append(f"  [{label}] {item.check}: {item.detail}")
            if item.severity in ("error", "warning") and item.fix:
                lines.append(f"         fix: {item.fix}")
        status = "red" if self.has_errors else ("yellow" if self.has_warnings else "green")
        lines.append(f"result: {status}")
        return "\n".join(lines)


# ── Individual checks ─────────────────────────────────────────────────


def _check_tasks_root(tasks_root: Path) -> CompletenessItem:
    if not tasks_root.exists():
        return CompletenessItem(
            check="tasks_root",
            severity="error",
            detail=f"{tasks_root} does not exist",
            fix=f"mkdir -p {tasks_root}",
        )
    if not os.access(tasks_root, os.W_OK):
        return CompletenessItem(
            check="tasks_root",
            severity="error",
            detail=f"{tasks_root} is not writable",
            fix=f"chmod +w {tasks_root}",
        )
    return CompletenessItem(
        check="tasks_root", severity="ok", detail=str(tasks_root),
    )


def _check_doc(label: str, path: Path) -> CompletenessItem:
    if path.exists():
        return CompletenessItem(check=label, severity="ok", detail=str(path))
    parent = path.parent
    if parent.exists() and os.access(parent, os.W_OK):
        return CompletenessItem(
            check=label,
            severity="warning",
            detail=f"{path} missing (parent is writable; bootstrap can synthesize)",
            fix=f"echo '# {path.stem}' > {path}",
        )
    return CompletenessItem(
        check=label,
        severity="error",
        detail=f"{path} missing and parent dir {parent} is not writable",
        fix=f"mkdir -p {parent} && touch {path}",
    )


def _check_send_script(send_script: Path) -> CompletenessItem:
    if not send_script.exists():
        return CompletenessItem(
            check="send_script",
            severity="error",
            detail=f"{send_script} does not exist",
            fix="verify profile.send_script path + re-clone ClawSeat if needed",
        )
    if not os.access(send_script, os.X_OK):
        return CompletenessItem(
            check="send_script",
            severity="error",
            detail=f"{send_script} is not executable",
            fix=f"chmod +x {send_script}",
        )
    return CompletenessItem(check="send_script", severity="ok", detail=str(send_script))


def _check_planner_brief(
    planner_brief_path: Path | None,
    tasks_root: Path,
    has_planner_seat: bool,
) -> list[CompletenessItem]:
    if not has_planner_seat:
        return [CompletenessItem(
            check="planner_brief", severity="info",
            detail="no planner seat declared — planner_brief not required",
        )]
    # Default path if the profile didn't spell it out.
    if planner_brief_path is None:
        planner_brief_path = tasks_root / "planner" / "PLANNER_BRIEF.md"
    if planner_brief_path.exists():
        return [CompletenessItem(
            check="planner_brief", severity="ok", detail=str(planner_brief_path),
        )]
    # Walk up to find the closest existing ancestor. If that ancestor is
    # writable we can `mkdir -p` + seed the brief, which is a warning.
    # Only when there is no writable ancestor at all does it become an error.
    ancestor = planner_brief_path.parent
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if ancestor.exists() and os.access(ancestor, os.W_OK):
        return [CompletenessItem(
            check="planner_brief",
            severity="warning",
            detail=(
                f"{planner_brief_path} missing (writable ancestor {ancestor} "
                "found; seed it before planner boot)"
            ),
            fix=(
                f"mkdir -p {planner_brief_path.parent} && echo '# PLANNER_BRIEF for "
                f"{tasks_root.name}' > {planner_brief_path}"
            ),
        )]
    return [CompletenessItem(
        check="planner_brief",
        severity="error",
        detail=(
            f"{planner_brief_path} missing and no writable ancestor found "
            f"(closest existing: {ancestor})"
        ),
        fix=f"mkdir -p {planner_brief_path.parent} && touch {planner_brief_path}",
    )]


def _check_project_binding(bindings_root: Path, project: str) -> CompletenessItem:
    binding_path = bindings_root / project / "PROJECT_BINDING.toml"
    if binding_path.exists():
        return CompletenessItem(
            check="project_binding", severity="ok", detail=str(binding_path),
        )
    return CompletenessItem(
        check="project_binding",
        severity="warning",
        detail=(
            f"{binding_path} missing — Feishu closeout paths will fail strict "
            "group resolution until this lands"
        ),
        fix=(
            f"agent-admin project bind --project {project} --group oc_... "
            "(or let the koder frontstage skill capture it during install)"
        ),
    )


# ── Public entry point ────────────────────────────────────────────────


def evaluate_profile(profile: Any, *, bindings_root: Path | None = None) -> CompletenessReport:
    """Run all completeness checks against a loaded HarnessProfile.

    ``bindings_root`` defaults to the operator's ``~/.agents/tasks`` via
    the same resolver the C2 binding helper uses; tests can inject a
    tmp-path override.
    """
    project = profile.project_name
    report = CompletenessReport(project=project)

    report.items.append(_check_tasks_root(Path(profile.tasks_root)))
    report.items.append(_check_doc("project_doc", Path(profile.project_doc)))
    report.items.append(_check_doc("tasks_doc", Path(profile.tasks_doc)))
    report.items.append(_check_doc("status_doc", Path(profile.status_doc)))
    report.items.append(_check_send_script(Path(profile.send_script)))

    seats = list(getattr(profile, "seats", []) or [])
    runtime = list(getattr(profile, "runtime_seats", None) or [])
    has_planner = ("planner" in seats) or ("planner" in runtime)

    # planner_brief_path may live at [patrol] in the profile TOML — not
    # surfaced on HarnessProfile today, so re-read if the profile exposes it.
    planner_brief_path: Path | None = getattr(profile, "planner_brief_path", None)
    if planner_brief_path is not None:
        planner_brief_path = Path(planner_brief_path).expanduser()
    report.items.extend(
        _check_planner_brief(planner_brief_path, Path(profile.tasks_root), has_planner)
    )

    if bindings_root is None:
        try:
            from project_binding import bindings_root as _br
            bindings_root = _br()
        except Exception:
            # Worst case: skip the binding check rather than crash.
            return report
    report.items.append(_check_project_binding(Path(bindings_root), project))

    # Info signals.
    report.items.append(CompletenessItem(
        check="heartbeat_owner", severity="info",
        detail=(
            f"{profile.heartbeat_owner} "
            f"(transport={getattr(profile, 'heartbeat_transport', 'n/a')})"
        ),
    ))
    report.items.append(CompletenessItem(
        check="seats", severity="info",
        detail=f"{len(seats)} declared: {', '.join(seats) if seats else '(none)'}",
    ))

    return report
