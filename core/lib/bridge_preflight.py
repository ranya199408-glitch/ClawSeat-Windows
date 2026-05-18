"""Bridge preflight (C3): fail-fast validation before launching a seat.

For any seat that participates in the Feishu bridge — currently the
project's ``active_loop_owner`` (planner) and its ``heartbeat_owner``
(koder/frontstage in OpenClaw mode) — we refuse to start the tmux
session until three things are green:

1. Per-project Feishu group resolves strictly (no guessing).
2. ``lark-cli auth status`` reports ``valid``.
3. A synthetic ``OC_DELEGATION_REPORT_V1`` envelope renders without
   raising (so the seat won't discover schema drift mid-task).

The result is returned as a dataclass; callers decide whether to abort.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


_FEISHU_DISABLED_ENV = "CLAWSEAT_FEISHU_ENABLED"
_FEISHU_DISABLED_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass
class PreflightCheck:
    name: str
    ok: bool
    detail: str
    fix: str = ""


@dataclass
class PreflightResult:
    project: str
    seat: str
    checks: list[PreflightCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def render(self) -> str:
        lines = [f"bridge-preflight project={self.project} seat={self.seat}"]
        for check in self.checks:
            marker = "OK" if check.ok else "FAIL"
            lines.append(f"  [{marker}] {check.name}: {check.detail}")
            if not check.ok and check.fix:
                lines.append(f"         fix: {check.fix}")
        lines.append("result: " + ("green" if self.ok else "RED — seat launch blocked"))
        return "\n".join(lines)


# Seat roles that participate in the Feishu bridge. Other seats
# (builder/reviewer/patrol) use tmux notify and do not need the preflight.
_BRIDGE_ROLES = frozenset({
    "planner-dispatcher",
    "frontstage-supervisor",
})


def seat_participates_in_bridge(
    *,
    seat: str,
    role: str,
    heartbeat_owner: str,
    active_loop_owner: str,
    heartbeat_transport: str,
) -> bool:
    """True when *seat* should run the bridge preflight."""
    if role in _BRIDGE_ROLES:
        return True
    if seat == active_loop_owner:
        return True
    # heartbeat_owner in tmux mode is just the koder TUI — no Feishu send.
    if seat == heartbeat_owner and heartbeat_transport == "openclaw":
        return True
    return False


# ── The three checks ──────────────────────────────────────────────────


def _check_group_resolution(project: str) -> PreflightCheck:
    """Import and call _feishu.resolve_feishu_group_strict(project)."""
    try:
        # Keep the import local so bridge_preflight has no static dependency
        # on the gstack-harness scripts namespace (test isolation).
        import importlib.util
        scripts_dir = (
            Path(__file__).resolve().parents[1]
            / "skills" / "gstack-harness" / "scripts"
        )
        spec = importlib.util.spec_from_file_location(
            "_feishu_preflight", scripts_dir / "_feishu.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        # _feishu imports _utils / real_home from its sibling paths.
        for path in (
            str(scripts_dir),
            str(Path(__file__).resolve().parent),  # core/lib/ itself
        ):
            if path not in sys.path:
                sys.path.insert(0, path)
        spec.loader.exec_module(module)
    except Exception as exc:
        return PreflightCheck(
            name="group_resolution",
            ok=False,
            detail=f"could not import _feishu: {exc!r}",
            fix="check core/skills/gstack-harness/scripts/_feishu.py",
        )
    try:
        group_id, source = module.resolve_feishu_group_strict(project)
    except module.FeishuGroupResolutionError as exc:
        return PreflightCheck(
            name="group_resolution",
            ok=False,
            detail=str(exc),
            fix=(
                "run `agent-admin project bind --project "
                f"{project} --group oc_...` to write the binding SSOT"
            ),
        )
    return PreflightCheck(
        name="group_resolution",
        ok=True,
        detail=f"project={project} -> {group_id} (source={source})",
    )


def _check_lark_cli_auth() -> PreflightCheck:
    """Call send_delegation_report.py --check-auth and inspect the result."""
    scripts_dir = (
        Path(__file__).resolve().parents[1]
        / "skills" / "gstack-harness" / "scripts"
    )
    script = scripts_dir / "send_delegation_report.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--check-auth"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return PreflightCheck(
            name="lark_cli_auth",
            ok=False,
            detail="--check-auth hung > 15s",
            fix="kill stuck lark-cli / check network",
        )
    except FileNotFoundError as exc:
        return PreflightCheck(
            name="lark_cli_auth",
            ok=False,
            detail=f"cannot execute --check-auth: {exc}",
            fix=f"verify {script} exists and is executable",
        )
    stdout = proc.stdout.strip()
    ok = proc.returncode == 0 and '"status": "ok"' in stdout
    if ok:
        return PreflightCheck(
            name="lark_cli_auth",
            ok=True,
            detail=stdout.splitlines()[-1] if stdout else "status=ok",
        )
    return PreflightCheck(
        name="lark_cli_auth",
        ok=False,
        detail=(proc.stderr.strip() or stdout or "unknown failure")[:400],
        fix="lark-cli auth login",
    )


def _check_envelope_renders(project: str, seat: str) -> PreflightCheck:
    """Build a synthetic OC_DELEGATION_REPORT_V1 envelope and confirm no
    schema errors. Catches drift in build_delegation_report_text() at
    start-up rather than after the seat has done real work."""
    try:
        import importlib.util
        scripts_dir = (
            Path(__file__).resolve().parents[1]
            / "skills" / "gstack-harness" / "scripts"
        )
        spec = importlib.util.spec_from_file_location(
            "_feishu_envelope", scripts_dir / "_feishu.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        envelope = module.build_delegation_report_text(
            project=project,
            lane="planning",
            task_id="preflight-check",
            dispatch_nonce=module.stable_dispatch_nonce(project, "planning", "preflight"),
            report_status="in_progress",
            decision_hint="proceed",
            user_gate="none",
            next_action="wait",
            summary=f"bridge preflight from seat={seat}",
            human_summary=None,
        )
    except Exception as exc:
        return PreflightCheck(
            name="envelope_render",
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
            fix="check build_delegation_report_text in _feishu.py",
        )
    if "OC_DELEGATION_REPORT_V1" not in envelope:
        return PreflightCheck(
            name="envelope_render",
            ok=False,
            detail="rendered envelope missing OC_DELEGATION_REPORT_V1 header",
            fix="check DELEGATION_REPORT_HEADER constant",
        )
    return PreflightCheck(
        name="envelope_render",
        ok=True,
        detail=f"envelope ok ({len(envelope)} bytes)",
    )


# ── Public API ────────────────────────────────────────────────────────


def _feishu_disabled() -> bool:
    """True if operator has opted out of Feishu via env var.

    The bridge preflight validates Feishu group binding + lark-cli auth +
    envelope schema — all of which are Feishu-specific. When the operator
    sets ``CLAWSEAT_FEISHU_ENABLED=0`` (or false/no/off) they have
    explicitly declared "this install does not participate in Feishu,"
    so blocking seat startup on Feishu readiness is wrong.
    """
    raw = os.environ.get(_FEISHU_DISABLED_ENV, "").strip().lower()
    return raw in _FEISHU_DISABLED_VALUES


def run_bridge_preflight(
    *,
    project: str,
    seat: str,
    skip_auth: bool = False,
    auth_checker: Callable[[], PreflightCheck] | None = None,
) -> PreflightResult:
    """Run the three preflight checks for *seat* in *project*.

    ``skip_auth`` lets tests bypass the lark-cli subprocess. ``auth_checker``
    lets tests inject a fake auth result without touching subprocess at all.

    Short-circuit: if ``CLAWSEAT_FEISHU_ENABLED=0`` (see ``_feishu_disabled``),
    every check is marked ok + "skipped" and the result is green. No Feishu
    network I/O is performed.
    """
    result = PreflightResult(project=project, seat=seat)
    if _feishu_disabled():
        skip_detail = f"skipped: {_FEISHU_DISABLED_ENV}=0"
        # Names must match the normal-path check names exactly so callers
        # that key off PreflightCheck.name don't see mode-dependent schema.
        for name in ("group_resolution", "lark_cli_auth", "envelope_render"):
            result.checks.append(
                PreflightCheck(name=name, ok=True, detail=skip_detail)
            )
        return result
    result.checks.append(_check_group_resolution(project))
    if skip_auth:
        PLACEHOLDER(
            PreflightCheck(name="lark_cli_auth", ok=True, detail="skipped by caller")
        )
    elif auth_checker is not None:
        result.checks.append(auth_checker())
    else:
        result.checks.append(_check_lark_cli_auth())
    result.checks.append(_check_envelope_renders(project, seat))
    return result
