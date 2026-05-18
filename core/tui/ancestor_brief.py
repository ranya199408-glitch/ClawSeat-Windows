"""Render the memory bootstrap brief — ANCESTOR_BOOTSTRAP.md per project.

Spec: docs/schemas/memory-bootstrap-brief.md (v0.1 schema, v0.2 checklist).

The renderer is pure-function shaped: given a resolved project context,
it emits a Markdown file with a leading YAML front-matter block. No side
effects beyond the one file write. It does NOT launch memory; that's
the launcher preflight's job.

Called by:
    core/launchers/agent-launcher.sh  (memory-preflight, Phase 2 2026-04-22)

Also callable standalone for debugging:
    python3 -m core.tui.ancestor_brief --project install --out /tmp/brief.md
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

from core.lib.real_home import real_user_home
from core.lib.tmux import tmux_session_alive as _tmux_session_alive  # noqa: E402

try:
    import tomllib
except ImportError:  # Python <3.11
    import tomli as tomllib  # type: ignore[no-redef]


BRIEF_SCHEMA_NAME = "memory-bootstrap"
BRIEF_SCHEMA_VERSION = "0.1"
# Canonical generator tag — architect looks for this to verify a brief
# came from the sanctioned renderer (not a hand-written file).
BRIEF_GENERATOR = "core/tui/ancestor_brief.py"

# Keep in sync with docs/schemas/memory-bootstrap-brief.md §Phase-A checklist.
# v0.1.1 (architect edit 2026-04-21): B8 removed (no operator-ack gate;
# Phase A → B is automatic). B2 widened to "verify-or-launch" (ancestor
# may auto-spawn memory if missing). B5 narrowed to "verify-binding"
# (binding came in via wizard during launcher preflight, not ancestor prompt).
DEFAULT_PHASE_A_CHECKLIST: tuple[str, ...] = (
    "B1-read-brief",
    "B2-verify-or-launch-memory",
    "B3-verify-openclaw-binding",
    "B4-launch-pending-seats",
    "B5-verify-feishu-group-binding",
    "B6-smoke-dispatch",
    "B7-write-status-ready",
)

# Default Feishu event whitelist — mirrored from v0.4 §4 canonical profile.
# The launcher's memory-preflight may pass an override sourced from profile.observability.
DEFAULT_FEISHU_EVENTS: tuple[str, ...] = (
    "task.completed",
    "chain.closeout",
    "seat.blocked_on_modal",
    "seat.context_near_limit",
)


@dataclasses.dataclass
class SeatDeclaration:
    role: str                           # one of LEGAL_SEATS
    sessions: list[str]                 # one entry per runtime instance (N>=1 for parallel-able roles)
    tool: str
    auth_mode: str
    provider: str
    parallel_instances: int | None = None  # only builder/reviewer/patrol
    # state aggregates across `sessions`:
    #   alive   — every session passes tmux has-session
    #   pending — one or more sessions not yet alive (first boot or partial spawn)
    #   dead    — explicit failure flag (reserved; renderer emits alive|pending today)
    state: str = "pending"

    def as_yaml_lines(self, indent: str = "    ") -> list[str]:
        sessions_inline = "[" + ", ".join(self.sessions) + "]"
        lines = [f"{indent[:-2]}- role: {self.role}",
                 f"{indent}sessions: {sessions_inline}",
                 f"{indent}tool: {self.tool}",
                 f"{indent}auth_mode: {self.auth_mode}",
                 f"{indent}provider: {self.provider}"]
        if self.parallel_instances is not None:
            lines.append(f"{indent}parallel_instances: {self.parallel_instances}")
        lines.append(f"{indent}state: {self.state}")
        return lines


@dataclasses.dataclass
class BriefContext:
    project: str
    profile_path: Path
    profile_version: int                # must be 2 for v0.4
    machine_config_path: Path | None    # None when machine.toml missing
    openclaw_tenant: str
    openclaw_tenant_workspace: Path
    feishu_group_binding: Path | None   # None → PROJECT_BINDING.toml not yet written
    seats: list[SeatDeclaration]
    machine_services_required: list[str]
    clawseat_root: Path
    patrol_cadence_minutes: int = 30
    feishu_events_whitelist: tuple[str, ...] = DEFAULT_FEISHU_EVENTS
    feishu_lark_cli_identity: str = "planner"  # §5 — shared identity decision


# ─────────────────────────────────────────────────────────────────────
# Path & session probes — read-only; never mutate anything
# _tmux_session_alive is imported from core.lib.tmux (audit §10.5)
# ─────────────────────────────────────────────────────────────────────

def _render_path(p: Path | None) -> str:
    if p is None:
        return "null"
    s = str(p)
    home = str(real_user_home())
    if s.startswith(home):
        return "~" + s[len(home):]
    return s


# ─────────────────────────────────────────────────────────────────────
# Context loader — turn a project name + profile path into a BriefContext
# ─────────────────────────────────────────────────────────────────────

def load_context_from_profile(
    *,
    project: str,
    profile_path: Path,
    machine_config_path: Path | None = None,
    clawseat_root: Path | None = None,
) -> BriefContext:
    """Build a BriefContext by reading the v2 profile TOML directly.

    Intentional lightweight implementation — the wizard's write_validated
    has already ensured the profile is well-formed, so we trust the fields
    we read rather than re-validating here.
    """
    raw = tomllib.loads(profile_path.read_text(encoding="utf-8"))
    if raw.get("version") != 2:
        raise ValueError(
            f"profile at {profile_path} is not v2 (got version={raw.get('version')!r}); "
            "run `scripts/install.sh --reinstall <project>` first"
        )
    profile_project = raw.get("project_name") or raw.get("profile_name")
    if profile_project != project:
        raise ValueError(
            f"profile project_name {profile_project!r} != requested {project!r}"
        )

    tenant = raw.get("openclaw_frontstage_agent", "")
    if not tenant:
        raise ValueError("profile missing openclaw_frontstage_agent")

    home = real_user_home()
    tenant_ws = home / ".openclaw" / f"workspace-{tenant}"

    seats_raw = raw.get("seats", [])
    seat_overrides = raw.get("seat_overrides", {}) or {}
    seats: list[SeatDeclaration] = []
    for raw_role in seats_raw:
        role = "patrol" if raw_role == "qa" else raw_role
        ov = seat_overrides.get(role) or seat_overrides.get(raw_role, {}) or {}
        sessions = _session_names(project, role, ov)
        parallel = ov.get("parallel_instances") if role in {"builder", "reviewer", "patrol", "qa"} else None
        # State across sessions: alive iff EVERY session passes has-session;
        # any miss → pending (B4 will spawn the gaps).
        state = "alive" if all(_tmux_session_alive(s) for s in sessions) else "pending"
        seats.append(SeatDeclaration(
            role=role,
            sessions=sessions,
            tool=ov.get("tool", "claude"),
            auth_mode=ov.get("auth_mode", "oauth_token"),
            provider=ov.get("provider", "anthropic"),
            parallel_instances=parallel,
            state=state,
        ))

    machine_services = list(raw.get("machine_services", ["memory"]))

    observability = raw.get("observability", {}) or {}
    whitelist = tuple(observability.get("announce_event_types", DEFAULT_FEISHU_EVENTS))

    patrol = raw.get("patrol", {}) or {}
    cadence = int(patrol.get("cadence_minutes", 30))

    if clawseat_root is None:
        env_root = os.environ.get("CLAWSEAT_ROOT")
        clawseat_root = Path(env_root).expanduser() if env_root else (home / ".clawseat")

    feishu_binding = home / ".agents" / "tasks" / project / "PROJECT_BINDING.toml"
    feishu_binding_final: Path | None = feishu_binding if feishu_binding.is_file() else None

    return BriefContext(
        project=project,
        profile_path=profile_path,
        profile_version=2,
        machine_config_path=machine_config_path if (machine_config_path and machine_config_path.is_file()) else None,
        openclaw_tenant=tenant,
        openclaw_tenant_workspace=tenant_ws,
        feishu_group_binding=feishu_binding_final,
        seats=seats,
        machine_services_required=machine_services,
        clawseat_root=clawseat_root,
        patrol_cadence_minutes=cadence,
        feishu_events_whitelist=whitelist,
    )


_FAN_OUT_ROLES = frozenset({"builder", "reviewer", "patrol", "qa"})


def _session_names(project: str, role: str, overrides: dict[str, Any]) -> list[str]:
    """Canonical tmux session name(s) per role.

    - Fan-out-capable roles (builder/reviewer/patrol) always get `<project>-<role>-<N>-<tool>`
      with one entry per `parallel_instances` (default 1 → still `<role>-1-<tool>`).
      Matches operator-machine convention: install-builder-1-claude,
      install-reviewer-1-codex etc.
    - Singletons (ancestor/planner/designer) get `<project>-<role>-<tool>` (no N).
    """
    tool = overrides.get("tool", "claude")
    if role in _FAN_OUT_ROLES:
        n = int(overrides.get("parallel_instances", 1) or 1)
        n = max(1, n)
        return [f"{project}-{role}-{i}-{tool}" for i in range(1, n + 1)]
    return [f"{project}-{role}-{tool}"]


# ─────────────────────────────────────────────────────────────────────
# Renderer — produces the markdown+YAML file content
# ─────────────────────────────────────────────────────────────────────

def render_brief(ctx: BriefContext) -> str:
    now_iso = _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")

    yaml_lines: list[str] = [
        "---",
        f"brief_schema: {BRIEF_SCHEMA_NAME}",
        f'brief_schema_version: "{BRIEF_SCHEMA_VERSION}"',
        f"brief_generated_at: {now_iso}",
        f"brief_generator: {BRIEF_GENERATOR}",
        "",
        f"project: {ctx.project}",
        f"profile_path: {_render_path(ctx.profile_path)}",
        f"profile_version: {ctx.profile_version}",
        f"machine_config_path: {_render_path(ctx.machine_config_path)}",
        f"openclaw_tenant: {ctx.openclaw_tenant}",
        f"openclaw_tenant_workspace: {_render_path(ctx.openclaw_tenant_workspace)}",
        f"feishu_group_binding: {_render_path(ctx.feishu_group_binding)}",
        "",
        "seats_declared:",
    ]
    for s in ctx.seats:
        yaml_lines.extend(s.as_yaml_lines())
    yaml_lines.append("")
    yaml_lines.append("machine_services_required:")
    for name in ctx.machine_services_required:
        yaml_lines.append(f"  - {name}")
    yaml_lines.append("")
    yaml_lines.append("checklist_phase_a:")
    for token in DEFAULT_PHASE_A_CHECKLIST:
        yaml_lines.append(f"  - {token}")
    yaml_lines.append("")
    yaml_lines.append(f"checklist_phase_b_cadence_minutes: {ctx.patrol_cadence_minutes}")
    yaml_lines.append("")
    yaml_lines.append("observability:")
    yaml_lines.append("  feishu_events_whitelist:")
    for evt in ctx.feishu_events_whitelist:
        yaml_lines.append(f"    - {evt}")
    yaml_lines.append('  feishu_sender_seat: memory')
    yaml_lines.append(f"  feishu_lark_cli_identity: {ctx.feishu_lark_cli_identity}")
    yaml_lines.append("")
    yaml_lines.append(f"clawseat_root: {_render_path(ctx.clawseat_root)}")
    yaml_lines.append("---")
    yaml_lines.append("")

    narrative = textwrap.dedent(f"""
    # Ancestor bootstrap brief — {ctx.project}

    This file is the handoff from the launcher to the memory seat.
    Ancestor reads it on first boot, executes the Phase-A checklist
    (`B1..B7` — B8 was removed in v0.2; memory enters Phase-B
    immediately after B7), then runs steady-state patrol (Phase B).
    Do not edit this file — it is regenerated on each install and its
    format is the memory skill's contract.

    **Your role summary** (full spec: `core/skills/clawseat-memory/SKILL.md`):
    - You are the project-level patrol + lifecycle owner.
    - You NEVER upgrade to koder. You NEVER retire.
    - You talk to operators only via Feishu, using `planner`'s lark-cli
      identity with `sender_seat: memory` header in each envelope.
    - You own seat lifecycle (add/remove/reconfigure/restart); koder does
      not. Seat lifecycle requests route operator → koder → planner → you.

    ## Phase-A checklist recap

    Execute in order. Each token has an exact contract documented in
    `docs/schemas/memory-bootstrap-brief.md §Phase-A checklist token
    semantics`. Skip steps whose idempotency predicate says "already done".

    ## Phase-B patrol recap

    After B7 writes STATUS.md you enter Phase-B. Patrol is
    **manual-by-default** — run one P1..P7 cycle when operator asks via
    natural-language trigger ("巡检" / "patrol" / "稳态检查" /
    "scan seats" / "Phase-B patrol" / "liveness check"); see memory
    skill §3.0. Optionally, if the project was installed with
    `install.sh --enable-auto-patrol`, an external `launchd` plist
    injects the same natural-language request every
    `{ctx.patrol_cadence_minutes}` minutes. The `/patrol-tick` slash
    token is deprecated — Claude Code's slash resolver rejects
    unregistered `/xxx` tokens as "Unknown command". You do not run an
    in-process sleep loop.

    ## Resources

    - Launcher: `{ctx.clawseat_root}/core/launchers/agent-launcher.sh`
    - iTerm driver (for operator-requested monitor windows): `{ctx.clawseat_root}/core/scripts/iterm_panes_driver.py`
    - Profile validator: `{ctx.clawseat_root}/core/lib/profile_validator.py`
    - Your skill: `{ctx.clawseat_root}/core/skills/clawseat-memory/SKILL.md`
    """).strip()

    return "\n".join(yaml_lines) + narrative + "\n"


def write_brief(ctx: BriefContext, out_path: Path | None = None) -> Path:
    if out_path is None:
        home = real_user_home()
        out_path = home / ".agents" / "tasks" / ctx.project / "patrol" / "handoffs" / "memory-bootstrap.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_brief(ctx), encoding="utf-8")
    return out_path


# ─────────────────────────────────────────────────────────────────────
# CLI entrypoint
# ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render memory bootstrap brief (v0.1)")
    parser.add_argument("--project", required=True, help="project name")
    parser.add_argument("--profile", type=Path, help="v2 profile path (defaults to ~/.agents/profiles/<project>-profile-dynamic.toml)")
    parser.add_argument("--machine-config", type=Path, help="machine.toml path (default: ~/.clawseat/machine.toml if exists)")
    parser.add_argument("--out", type=Path, help="output path (default: ~/.agents/tasks/<project>/patrol/handoffs/memory-bootstrap.md)")
    parser.add_argument("--dry-run", action="store_true", help="print to stdout instead of writing")
    parser.add_argument("--json-context", action="store_true", help="print the parsed context as JSON (for debugging)")
    args = parser.parse_args(argv)

    home = real_user_home()
    profile_path = args.profile or (home / ".agents" / "profiles" / f"{args.project}-profile-dynamic.toml")
    if not profile_path.is_file():
        print(f"error: profile not found: {profile_path}", file=sys.stderr)
        return 2
    machine_cfg = args.machine_config or (home / ".clawseat" / "machine.toml")
    if not machine_cfg.is_file():
        machine_cfg = None

    try:
        ctx = load_context_from_profile(
            project=args.project,
            profile_path=profile_path,
            machine_config_path=machine_cfg,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.json_context:
        safe = dataclasses.asdict(ctx)
        # Paths aren't JSON-serializable
        safe["profile_path"] = str(ctx.profile_path)
        safe["machine_config_path"] = str(ctx.machine_config_path) if ctx.machine_config_path else None
        safe["openclaw_tenant_workspace"] = str(ctx.openclaw_tenant_workspace)
        safe["feishu_group_binding"] = str(ctx.feishu_group_binding) if ctx.feishu_group_binding else None
        safe["clawseat_root"] = str(ctx.clawseat_root)
        safe["feishu_events_whitelist"] = list(ctx.feishu_events_whitelist)
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        return 0

    rendered = render_brief(ctx)
    if args.dry_run:
        print(rendered, end="")
        return 0
    written = write_brief(ctx, args.out)
    print(f"wrote {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
