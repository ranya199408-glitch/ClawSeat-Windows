#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _common import (
    AGENTS_ROOT,
    HarnessProfile,
    REPO_ROOT,
    load_profile,
    make_local_override,
    materialize_profile_runtime,
    require_success,
    run_command,
    seed_empty_secret_from_peer,
)


def _link_sandbox_tasks_to_real_home(
    profile: HarnessProfile,
    seats: list[str],
    *,
    _agents_home: Path | None = None,
) -> None:
    """Per-project symlink. Covers all sub-paths including patrol/handoffs and
    per-seat TODO/DELIVERY atomically.

    Creates: sandbox_home/.agents/tasks/<project>  →  real profile.tasks_root

    Replaces the old per-seat approach with a single project-level symlink so
    patrol/handoffs, PROJECT.md, STATUS.md etc. are also visible across the
    sandbox boundary. Idempotent. Fail-safe: warns on error, never raises.

    Upgrade path from legacy per-seat symlinks:
      If sandbox_home/.agents/tasks/<project> is a real dir containing only
      per-seat symlinks (no real files/dirs), those symlinks are removed and
      the parent dir is replaced with the per-project symlink.
    """
    try:
        import tomllib as _tomllib
    except ModuleNotFoundError:
        import tomli as _tomllib  # type: ignore

    agents_home = _agents_home or AGENTS_ROOT
    real_tasks_root = profile.tasks_root
    real_tasks_root.mkdir(parents=True, exist_ok=True)

    seen_sandbox_homes: set[Path] = set()

    for seat in seats:
        session_path = agents_home / "sessions" / profile.project_name / seat / "session.toml"
        if not session_path.is_file():
            continue
        try:
            with open(session_path, "rb") as _f:
                session_data = _tomllib.load(_f)
        except Exception as exc:
            print(f"warn: _link_sandbox_tasks: cannot read session for {seat}: {exc}", file=sys.stderr)
            continue

        runtime_dir = session_data.get("runtime_dir", "")
        if not runtime_dir:
            continue
        sandbox_home = Path(runtime_dir) / "home"
        if not sandbox_home.is_dir():
            continue

        if sandbox_home in seen_sandbox_homes:
            continue
        seen_sandbox_homes.add(sandbox_home)

        sandbox_project_link = sandbox_home / ".agents" / "tasks" / profile.project_name

        try:
            if sandbox_project_link.is_symlink():
                if sandbox_project_link.resolve() == real_tasks_root.resolve():
                    continue  # already correct — idempotent
                print(
                    f"warn: _link_sandbox_tasks: {sandbox_project_link} is symlink to different target, skipping",
                    file=sys.stderr,
                )
                continue

            if sandbox_project_link.exists():
                # Real directory — inspect children
                children = list(sandbox_project_link.iterdir())
                real_items = [c for c in children if not c.is_symlink()]
                if real_items:
                    print(
                        f"warn: _link_sandbox_tasks: {sandbox_project_link} is regular dir with data, skipping",
                        file=sys.stderr,
                    )
                    continue
                # Only symlinks (or empty) — safe to migrate
                for child in children:
                    child.unlink()
                sandbox_project_link.rmdir()

            sandbox_project_link.parent.mkdir(parents=True, exist_ok=True)
            sandbox_project_link.symlink_to(real_tasks_root.resolve())
        except Exception as exc:
            print(f"warn: _link_sandbox_tasks: failed to link for {seat}: {exc}", file=sys.stderr)


def _sync_workspaces_host_to_sandbox(
    profile: HarnessProfile,
    seats: list[str],
    *,
    strict: bool = False,
    _agents_home: Path | None = None,
) -> None:
    """Rsync host workspace → sandbox workspace for each seat (add-only, never delete).

    Fixes split-brain: seats run inside a sandbox HOME that may not have TOOLS/
    written by init_koder on the host side. --ignore-existing preserves
    sandbox-specific files while seeding host canonical content into the sandbox.

    Prints per-seat:  workspace_sync: <seat> host=<p> sandbox=<p> files=<N> status=ok|skip|fail
    Fail-safe: warns on error, never raises (unless strict=True).
    """
    try:
        import tomllib as _tomllib
    except ModuleNotFoundError:
        import tomli as _tomllib  # type: ignore

    agents_home = _agents_home or AGENTS_ROOT

    for seat in seats:
        host_workspace = profile.workspace_root / seat
        if not host_workspace.is_dir():
            print(
                f"workspace_sync: {seat} status=skip reason=host_workspace_not_found host={host_workspace}"
            )
            continue

        session_path = agents_home / "sessions" / profile.project_name / seat / "session.toml"
        if not session_path.is_file():
            print(f"workspace_sync: {seat} status=skip reason=no_session")
            continue

        try:
            with open(session_path, "rb") as _f:
                session_data = _tomllib.load(_f)
        except Exception as exc:
            print(f"workspace_sync: {seat} status=skip reason=session_read_error: {exc}")
            continue

        runtime_dir = session_data.get("runtime_dir", "")
        if not runtime_dir:
            print(f"workspace_sync: {seat} status=skip reason=no_runtime_dir")
            continue

        sandbox_home = Path(runtime_dir) / "home"
        if not sandbox_home.is_dir():
            print(
                f"workspace_sync: {seat} status=skip reason=sandbox_home_not_found sandbox={sandbox_home}"
            )
            continue

        sandbox_workspace = sandbox_home / ".agents" / "workspaces" / profile.project_name / seat
        sandbox_workspace.mkdir(parents=True, exist_ok=True)

        # rsync: append-only (--ignore-existing), preserve attrs (-a)
        src = str(host_workspace).rstrip("/") + "/"
        dst = str(sandbox_workspace).rstrip("/") + "/"

        try:
            result = subprocess.run(
                ["rsync", "-a", "--ignore-existing", src, dst],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                transferred = [
                    ln for ln in result.stdout.splitlines()
                    if ln and not ln.startswith("sent") and not ln.startswith("total")
                ]
                print(
                    f"workspace_sync: {seat} host={host_workspace} sandbox={sandbox_workspace}"
                    f" files={len(transferred)} status=ok"
                )
            else:
                msg = (
                    f"workspace_sync: {seat} host={host_workspace} sandbox={sandbox_workspace}"
                    f" status=fail rc={result.returncode}"
                )
                if strict:
                    raise RuntimeError(msg)
                print(f"warn: {msg}", file=sys.stderr)
        except FileNotFoundError:
            msg = f"workspace_sync: {seat} status=fail reason=rsync_not_found"
            if strict:
                raise RuntimeError(msg)
            print(f"warn: {msg}", file=sys.stderr)
        except RuntimeError:
            raise
        except Exception as exc:
            msg = f"workspace_sync: {seat} status=fail reason={exc}"
            if strict:
                raise RuntimeError(msg)
            print(f"warn: {msg}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap a project from a gstack harness profile.")
    parser.add_argument("--profile", required=True, help="Path to the project profile TOML.")
    parser.add_argument("--project-name", help="Override project name from the profile.")
    parser.add_argument("--repo-root", help="Override repo root from the profile.")
    parser.add_argument("--start", action="store_true", help="Start the project monitor after bootstrap.")
    parser.add_argument("--refresh-existing", action="store_true", help="Refresh workspace files for already-deployed seats from current template.")
    parser.add_argument("--link-tasks", action="store_true", help="Only create sandbox→real tasks symlinks (skip full bootstrap).")
    parser.add_argument("--no-workspace-sync", action="store_true", help="Skip host→sandbox workspace rsync step.")
    parser.add_argument("--strict-workspace-sync", action="store_true", help="Abort bootstrap if any workspace rsync fails.")
    parser.add_argument(
        "--strict-completeness",
        action="store_true",
        help=(
            "Treat bootstrap-completeness warnings (missing PLANNER_BRIEF.md, "
            "missing PROJECT_BINDING.toml, etc.) as hard failures. Default: "
            "warnings are logged but do not block the bootstrap."
        ),
    )
    parser.add_argument(
        "--skip-completeness",
        action="store_true",
        help="Skip the post-bootstrap completeness check entirely.",
    )
    return parser.parse_args()


def with_overrides(profile: HarnessProfile, *, project_name: str, repo_root: Path) -> HarnessProfile:
    if project_name == profile.project_name and repo_root == profile.repo_root:
        return profile
    tasks_root = repo_root / ".tasks"
    return HarnessProfile(
        profile_path=profile.profile_path,
        profile_name=profile.profile_name,
        template_name=profile.template_name,
        project_name=project_name,
        repo_root=repo_root,
        tasks_root=tasks_root,
        project_doc=tasks_root / "PROJECT.md",
        tasks_doc=tasks_root / "TASKS.md",
        status_doc=tasks_root / "STATUS.md",
        send_script=profile.send_script,
        status_script=tasks_root / "patrol" / "check-status.sh",
        patrol_script=tasks_root / "patrol" / "patrol-supervisor.sh",
        agent_admin=profile.agent_admin,
        workspace_root=profile.workspace_root.parent / project_name,
        handoff_dir=tasks_root / "patrol" / "handoffs",
        heartbeat_owner=profile.heartbeat_owner,
        heartbeat_transport=profile.heartbeat_transport,
        active_loop_owner=profile.active_loop_owner,
        default_notify_target=profile.default_notify_target,
        heartbeat_receipt=(profile.workspace_root.parent / project_name / profile.heartbeat_owner / "HEARTBEAT_RECEIPT.toml"),
        seats=list(profile.seats),
        heartbeat_seats=list(profile.heartbeat_seats),
        seat_roles=dict(profile.seat_roles),
        seat_overrides={seat: dict(values) for seat, values in profile.seat_overrides.items()},
        dynamic_roster_enabled=profile.dynamic_roster_enabled,
        runtime_seats=list(profile.runtime_seats or []),
        session_root=profile.session_root,
        materialized_seats=list(profile.materialized_seats or []),
        bootstrap_seats=list(profile.bootstrap_seats or []),
        default_start_seats=list(profile.default_start_seats or []),
        compat_legacy_seats=profile.compat_legacy_seats,
        legacy_seats=list(profile.legacy_seats or []),
        legacy_seat_roles=dict(profile.legacy_seat_roles or {}),
    )


def main() -> int:
    args = parse_args()
    profile = load_profile(args.profile)
    project_name = args.project_name or profile.project_name
    repo_root = Path(args.repo_root).expanduser() if args.repo_root else profile.repo_root
    effective_profile = with_overrides(profile, project_name=project_name, repo_root=repo_root)
    runtime_seats = list(effective_profile.runtime_seats or effective_profile.materialized_seats or effective_profile.seats)

    if args.link_tasks:
        _link_sandbox_tasks_to_real_home(
            effective_profile,
            runtime_seats,
        )
        return 0

    # Validate skills before bootstrap — block on required missing
    try:
        import importlib.util as _ilu
        _sr_spec = _ilu.spec_from_file_location("skill_registry", str(REPO_ROOT / "core" / "skill_registry.py"))
        if _sr_spec and _sr_spec.loader:
            _sr = _ilu.module_from_spec(_sr_spec)
            # Python 3.12+ dataclass(slots=True) needs the module in sys.modules
            sys.modules.setdefault("skill_registry", _sr)
            _sr_spec.loader.exec_module(_sr)
            _sr_result = _sr.validate_all()
            for _si in _sr_result.required_missing:
                print(f"skill_blocked: {_si.name} ({_si.source}) — {_si.expanded_path}", file=sys.stderr)
                if _si.fix_hint:
                    print(f"  -> {_si.fix_hint}", file=sys.stderr)
            if _sr_result.required_missing:
                print(f"\nBootstrap aborted: {len(_sr_result.required_missing)} required skill(s) missing.", file=sys.stderr)
                return 1
            for _si in _sr_result.optional_missing:
                print(f"skill_warning: {_si.name} ({_si.source}) — {_si.expanded_path}", file=sys.stderr)
    except (ImportError, FileNotFoundError, OSError) as _exc:
        print(f"skill_check_skipped: {_exc}", file=sys.stderr)

    local_path = make_local_override(profile, project_name=project_name, repo_root=repo_root)
    try:
        cmd = [
            sys.executable,
            str(effective_profile.agent_admin),
            "project",
            "bootstrap",
            "--template",
            effective_profile.template_name,
            "--local",
            str(local_path),
        ]
        result = run_command(cmd, cwd=effective_profile.repo_root)
        require_success(result, "bootstrap_harness")
        materialize_profile_runtime(effective_profile)
        _link_sandbox_tasks_to_real_home(
            effective_profile,
            runtime_seats,
        )
        if not args.no_workspace_sync:
            _sync_workspaces_host_to_sandbox(
                effective_profile,
                runtime_seats,
                strict=args.strict_workspace_sync,
            )
        for seat in runtime_seats:
            seed_empty_secret_from_peer(effective_profile, seat)
            # OAuth is user-managed via the TUI; nothing to seed here.
        # C7: bootstrap completeness — run after seat/secret seeding so the
        # report sees the post-bootstrap shape. Warnings log to stderr and
        # allow progress by default; --strict-completeness converts them
        # into a hard abort. --skip-completeness disables the check.
        # Access via getattr so tests that pass a SimpleNamespace without
        # the new flags keep working (backward-compat with pre-C7 callers).
        _skip_completeness = getattr(args, "skip_completeness", False)
        _strict_completeness = getattr(args, "strict_completeness", False)
        if not _skip_completeness:
            try:
                import importlib.util as _bc_ilu
                _bc_spec = _bc_ilu.spec_from_file_location(
                    "bootstrap_completeness",
                    str(REPO_ROOT / "core" / "lib" / "bootstrap_completeness.py"),
                )
                assert _bc_spec and _bc_spec.loader
                _bc = _bc_ilu.module_from_spec(_bc_spec)
                _bc_spec.loader.exec_module(_bc)
                report = _bc.evaluate_profile(effective_profile)
                print(report.render(), file=sys.stderr)
                if report.has_errors or (_strict_completeness and report.has_warnings):
                    print(
                        "\nbootstrap aborted: completeness check "
                        + ("failed with errors" if report.has_errors else "warnings (strict mode)"),
                        file=sys.stderr,
                    )
                    return 1
            except Exception as _bc_exc:
                print(
                    f"bootstrap_completeness check skipped: {_bc_exc!r}",
                    file=sys.stderr,
                )

        if args.refresh_existing:
            for seat in (effective_profile.materialized_seats or effective_profile.seats):
                refresh_cmd = [
                    sys.executable, str(effective_profile.agent_admin),
                    "engineer", "refresh-workspace", seat,
                    "--project", project_name,
                ]
                refresh_result = run_command(refresh_cmd, cwd=effective_profile.repo_root)
                require_success(refresh_result, f"bootstrap_harness refresh-existing {seat}")
                if refresh_result.stdout.strip():
                    print(refresh_result.stdout.strip())
        if args.start:
            if effective_profile.heartbeat_transport == "openclaw":
                print(
                    "start_skipped: "
                    f"frontstage {effective_profile.heartbeat_owner!r} uses OpenClaw transport; "
                    "do not start a tmux session for the heartbeat owner during bootstrap."
                )
            else:
                start_result = run_command(
                    [
                        sys.executable,
                        str(effective_profile.agent_admin),
                        "session",
                        "start-engineer",
                        effective_profile.heartbeat_owner,
                        "--project",
                        project_name,
                    ],
                    cwd=effective_profile.repo_root,
                )
                require_success(start_result, "bootstrap_harness start frontstage")
                if start_result.stdout.strip():
                    print(start_result.stdout.strip())
                open_result = run_command(
                    [
                        sys.executable,
                        str(effective_profile.agent_admin),
                        "window",
                        "open-monitor",
                        project_name,
                    ],
                    cwd=effective_profile.repo_root,
                )
                require_success(open_result, "bootstrap_harness open-monitor")
        if result.stdout.strip():
            print(result.stdout.strip())
        return 0
    except Exception as exc:
        print(
            f"warn: bootstrap failed for {project_name!r}: {exc}\n"
            f"Rollback hint: remove workspace at {effective_profile.workspace_root}"
            f" and re-run bootstrap_harness, or run: python3 agent.py project"
            f" teardown --project {project_name}",
            file=sys.stderr,
        )
        raise
    finally:
        local_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
