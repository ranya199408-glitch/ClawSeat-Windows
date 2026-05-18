"""Heartbeat, runtime materialization, and token usage helpers."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from _utils import (
    AGENTS_ROOT,
    OPENCLAW_AGENTS_ROOT,
    REPO_ROOT,
    SCRIPTS_ROOT,
    ensure_dir,
    ensure_parent,
    load_toml,
    sanitize_name,
    utc_now_iso,
    write_text,
)

from .profile import HarnessProfile, render_project_doc, render_status_doc, render_tasks_doc

__all__ = [
    "tracked_runtime_seats",
    "heartbeat_manifest_path",
    "heartbeat_md_path",
    "is_managed_runtime_path",
    "make_local_override",
    "render_idle_todo",
    "render_status_wrapper",
    "render_patrol_wrapper",
    "render_heartbeat_md",
    "render_heartbeat_manifest",
    "_patch_claude_settings_from_profile",
    "materialize_profile_runtime",
]

def tracked_runtime_seats(profile: HarnessProfile) -> list[str]:
    return list(profile.tmux_runtime_seats())

def heartbeat_manifest_path(profile: HarnessProfile, seat: str) -> Path:
    return profile.workspace_for(seat) / "HEARTBEAT_MANIFEST.toml"

def heartbeat_md_path(profile: HarnessProfile, seat: str) -> Path:
    return profile.workspace_for(seat) / "HEARTBEAT.md"

def is_managed_runtime_path(profile: HarnessProfile, path: Path) -> bool:
    try:
        path.resolve().relative_to(profile.tasks_root.resolve())
        return True
    except ValueError:
        return False

def make_local_override(profile: HarnessProfile, *, project_name: str, repo_root: Path) -> Path:
    seat_order = list(profile.compat_materialized_seats())
    tmux_runtime_seats = list(profile.tmux_runtime_seats())
    lines = [
        "version = 1",
        "",
        f'project_name = "{project_name}"',
        f'repo_root = "{repo_root}"',
        "# Local override / legacy harness compatibility fields.",
        "# Layered v2 profiles do not store these keys directly.",
        f"seat_order = {json.dumps(seat_order)}",
        f"materialized_seats = {json.dumps(seat_order)}",
        f"runtime_seats = {json.dumps(tmux_runtime_seats)}",
        f"bootstrap_seats = {json.dumps(list(profile.bootstrap_seats or []))}",
        f"default_start_seats = {json.dumps(list(profile.default_start_seats or []))}",
        f'heartbeat_transport = "{profile.frontstage_transport_kind()}"',
    ]
    for seat_id, override in profile.seat_overrides.items():
        if not override:
            continue
        lines.extend(["", "[[overrides]]", f'id = "{seat_id}"'])
        for key, value in override.items():
            lines.append(f'{key} = "{value}"')
    payload = "\n".join(lines) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=f"{sanitize_name(project_name)}-", suffix=".toml")
    tmp_path = Path(tmp)
    os.close(fd)
    write_text(tmp_path, payload)
    return tmp_path

# ── Rendering ────────────────────────────────────────────────────────

def render_idle_todo(profile: HarnessProfile, seat: str) -> str:
    role = profile.seat_roles.get(seat, "specialist")
    if seat == profile.heartbeat_owner:
        reply_to = profile.default_notify_target
        title = "等待项目启动与群联调"
        objective = (
            f"{seat} template已初始化。若当前项目走 OpenClaw/Feishu 链路，且 planner 已经启动，"
            "请主动要求用户让 main agent 拉群并回报 group ID。无需 open_id。"
            "main 在群里保持 requireMention=true；项目面向前台的 koder 账号在该群里默认设为 requireMention=false，"
            "只有显式部署的系统 seat（如 warden）才需要额外放开。"
            "拿到 group ID 后，先确认该群绑定当前项目、已有项目还是新项目，再委派 planner 做飞书联调测试，"
            "提示用户\u201c收到测试消息即可回复希望完成什么任务\u201d，并并行拉起 reviewer 进入审查待命。"
        )
    elif seat == profile.active_loop_owner or role in {"planner", "planner-dispatcher"}:
        reply_to = profile.heartbeat_owner
        title = "等待 frontstage intake / 初始化广播"
        objective = (
            f"{seat} template已初始化。当前没有已派发任务。若你刚完成 planner 初始化，"
            "请尽快把 ready 状态回给 koder/frontstage，方便其完成项目绑定与 Feishu 群联调；"
            "若 frontstage 提供了 group ID 和项目绑定，请先完成群联调测试并向用户发送首条测试消息，提示其收到后直接回复希望完成什么任务；"
            "若当前链路是测试、验证、smoke 或回归重任务，请同步拉起 patrol-1 作为验证席位；"
            "否则先阅读 WORKSPACE_CONTRACT.toml 与 workspace guide，等待新的 dispatch。"
        )
    else:
        reply_to = profile.active_loop_owner
        title = "等待任务派发"
        objective = (
            f"{seat} template已初始化。当前没有已派发任务，先阅读 WORKSPACE_CONTRACT.toml 与 workspace guide，随后等待新的 dispatch。"
        )
    return (
        "task_id: null\n"
        f"project: {profile.project_name}\n"
        f"owner: {seat}\n"
        "status: pending\n"
        f"title: {title}\n\n"
        f"# Objective\n\n{objective}\n\n"
        "# Dispatch\n\n"
        "source: null\n"
        f"reply_to: {reply_to}\n"
    )

def render_status_wrapper(profile: HarnessProfile) -> str:
    seats = " ".join(tracked_runtime_seats(profile))
    return (
        "#!/bin/bash\n"
        "set -euo pipefail\n\n"
        f"export TASKS_ROOT={profile.tasks_root}\n"
        f"export PATROL_DIR={profile.tasks_root / 'patrol'}\n"
        f"export DEFAULT_SESSIONS=\"{seats}\"\n\n"
        f"export AGENT_PROJECT=\"{profile.project_name}\"\n\n"
        f'exec {SCRIPTS_ROOT / "check-engineer-status.sh"} "$@"\n'
    )

def render_patrol_wrapper(profile: HarnessProfile) -> str:
    return (
        "#!/bin/bash\n"
        "set -euo pipefail\n\n"
        f'exec python3 {REPO_ROOT / "core" / "skills" / "gstack-harness" / "scripts" / "patrol_supervisor.py"} --profile {profile.profile_path} "$@"\n'
    )

def render_heartbeat_md(profile: HarnessProfile, seat: str) -> str:
    role = profile.seat_roles.get(seat, "frontstage-supervisor")
    patrol_entry = profile.patrol_script
    status_entry = profile.status_script
    return (
        f"# {seat} heartbeat\n\n"
        f"Runtime seat id: `{seat}`\n"
        f"Canonical role: `{role}`\n\n"
        "Provisioning assets:\n\n"
        "- `HEARTBEAT_MANIFEST.toml` is the desired heartbeat contract.\n"
        "- `HEARTBEAT_RECEIPT.toml` is the framework-owned verified install receipt.\n\n"
        "When a scheduled heartbeat poll arrives:\n\n"
        "1. Stay in lightweight patrol mode; do not enter plan mode for a routine heartbeat run.\n"
        "2. Do not reload broad project strategy docs unless the classifier or patrol script returns an ambiguous contradiction that cannot be resolved from the scripted facts.\n"
        f"3. Run `{status_entry}` as the first-pass classifier.\n"
        f"4. Run `{patrol_entry}` to decide whether `{profile.active_loop_owner}` needs a reminder.\n"
        "5. If there is no meaningful state change, reply exactly `HEARTBEAT_OK`.\n"
        "6. If patrol shows a real delivery-not-consumed or stalled-seat condition, use the frontstage unblock authority to clear the procedural wait and remind the active loop owner if needed.\n"
        f"7. Only if the scripts fail or disagree, read the smallest necessary docs (`{profile.tasks_doc}` / `{profile.status_doc}` first) and return a short blocker summary instead of loading the full frontstage context.\n\n"
        "Reliable handoff model:\n\n"
        "- `assigned` = target `TODO.md` exists\n"
        "- `notified` = `send-and-verify.sh` returned success\n"
        "- `consumed` = target seat durable ACK exists in `TODO.md`\n"
        "- only `assigned + notified + consumed` counts as a healthy handoff\n\n"
        "Review verdict routing matrix:\n\n"
        f"- `APPROVED` / `APPROVED_WITH_NITS` -> `{profile.heartbeat_owner}`\n"
        "- `CHANGES_REQUESTED` -> builder seat (from profile `seat_roles`, or `active_loop_owner`)\n"
        f"- `BLOCKED` / `DECISION_NEEDED` -> `{profile.heartbeat_owner}`\n"
        f"- Reviewer seat delivers verdicts; `{profile.active_loop_owner}` chooses the next hop\n\n"
        "Guardrails:\n\n"
        f"- `{profile.active_loop_owner}` remains the active loop owner and decision owner.\n"
        f"- `{profile.heartbeat_owner}` owns confirmations, approvals, reminders, and other procedural unblock actions.\n"
        "- Do not write downstream specialist TODOs from a heartbeat run.\n"
        "- Keep heartbeat replies short and factual; avoid restating full project context on every poll.\n"
        "- If there is no real reminder to send, stay silent with `HEARTBEAT_OK`.\n"
    )

def render_heartbeat_manifest(profile: HarnessProfile, seat: str) -> str:
    commands = [
        str(profile.patrol_script),
        f"{profile.patrol_script} --send",
    ]
    workspace = profile.workspace_for(seat)
    receipt = profile.heartbeat_receipt_for(seat)
    lines = [
        "version = 1",
        f'seat_id = "{seat}"',
        f'project = "{profile.project_name}"',
        f'role = "{profile.seat_roles.get(seat, "frontstage-supervisor")}"',
        'kind = "heartbeat"',
        "enabled = true",
        "interval_minutes = 15",
        f'active_loop_owner = "{profile.active_loop_owner}"',
        'expected_idle_reply = "HEARTBEAT_OK"',
        f'workspace = "{workspace}"',
        f'repo_root = "{profile.repo_root}"',
        f'receipt_path = "{receipt}"',
        f'patrol_entrypoint = "{profile.status_script}"',
        f'supervisor_entrypoint = "{profile.patrol_script}"',
        f'send_script = "{profile.send_script}"',
        f'commands = {json.dumps(commands, ensure_ascii=False)}',
        "",
    ]
    return "\n".join(lines)

# ── Runtime materialization ──────────────────────────────────────────

def _patch_claude_settings_from_profile(profile: HarnessProfile, seats: list[str]) -> None:
    """Patch Claude settings with model, effortLevel, and hasCompletedOnboarding."""
    template_path = REPO_ROOT / "core" / "templates" / profile.template_name / "template.toml"
    if not template_path.exists():
        return
    template_data = load_toml(template_path)
    engineer_map: dict[str, dict] = {}
    for eng in template_data.get("engineers", []):
        engineer_map[str(eng.get("id", ""))] = eng

    sessions_root = Path(os.environ.get("SESSIONS_ROOT", str(AGENTS_ROOT / "sessions")))

    _admin_scripts = REPO_ROOT / "core" / "scripts"
    _provider_configs: dict = {}
    try:
        import importlib.util
        _spec = importlib.util.spec_from_file_location("agent_admin_config", _admin_scripts / "agent_admin_config.py")
        if _spec and _spec.loader:
            _mod = importlib.util.module_from_spec(_spec)
            import sys as _sys
            _sys.modules.setdefault("agent_admin_config", _mod)
            _spec.loader.exec_module(_mod)
            _provider_configs = getattr(_mod, "CLAUDE_API_PROVIDER_CONFIGS", {})
    except (ImportError, FileNotFoundError, OSError, AttributeError) as exc:
        # silent-ok: agent_admin_config is optional; fall back to empty provider list.
        import sys
        print(f"warn: agent_admin_config load failed: {exc}", file=sys.stderr)

    for seat in seats:
        spec = engineer_map.get(seat, {})
        model = str(spec.get("model", "")).strip()
        effort = str(spec.get("effort", "")).strip()
        auth_mode = str(spec.get("auth_mode", "")).strip()
        provider = str(spec.get("provider", "")).strip()
        session_path = sessions_root / profile.project_name / seat / "session.toml"
        runtime_dir = None
        if session_path.exists():
            session_data = load_toml(session_path)
            auth_mode = str(session_data.get("auth_mode", auth_mode)).strip()
            provider = str(session_data.get("provider", provider)).strip()
            runtime_dir = str(session_data.get("runtime_dir", "")).strip()
            tool = str(session_data.get("tool", "")).strip()
            if tool and tool != "claude":
                continue

        settings_path = profile.workspace_for(seat) / ".claude" / "settings.local.json"
        if settings_path.exists():
            try:
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                settings = {}
            changed = False
            if model and settings.get("model") != model:
                settings["model"] = model
                changed = True
            if auth_mode == "api" and not settings.get("hasCompletedOnboarding"):
                settings["hasCompletedOnboarding"] = True
                changed = True
            if changed:
                write_text(settings_path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")

        if runtime_dir:
            runtime_settings_path = Path(runtime_dir) / "home" / ".claude" / "settings.json"
            ensure_parent(runtime_settings_path)
            try:
                rt_settings = json.loads(runtime_settings_path.read_text(encoding="utf-8")) if runtime_settings_path.exists() else {}
            except (json.JSONDecodeError, OSError):
                rt_settings = {}
            rt_changed = False
            if model and rt_settings.get("model") != model:
                rt_settings["model"] = model
                rt_changed = True
            if effort and rt_settings.get("effortLevel") != effort:
                rt_settings["effortLevel"] = effort
                rt_changed = True
            if "skipDangerousModePermissionPrompt" not in rt_settings:
                rt_settings["skipDangerousModePermissionPrompt"] = True
                rt_changed = True
            prov_config = _provider_configs.get(provider, {})
            extra_env = prov_config.get("extra_env")
            if extra_env:
                env_block = rt_settings.get("env", {})
                if not isinstance(env_block, dict):
                    env_block = {}
                for env_key, env_val in extra_env.items():
                    if env_block.get(env_key) != env_val:
                        env_block[env_key] = env_val
                        rt_changed = True
                if env_block:
                    rt_settings["env"] = env_block
            if rt_changed:
                write_text(runtime_settings_path, json.dumps(rt_settings, indent=2, ensure_ascii=False) + "\n")

def materialize_profile_runtime(profile: HarnessProfile) -> None:
    ensure_dir(profile.tasks_root)
    ensure_dir(profile.handoff_dir)
    all_seats: list[str] = []
    for seat in [*profile.compat_materialized_seats(), *profile.declared_project_seats()]:
        if seat and seat not in all_seats:
            all_seats.append(seat)
    for seat in all_seats:
        ensure_dir(profile.tasks_root / seat)
        todo_path = profile.todo_path(seat)
        if not todo_path.exists():
            write_text(todo_path, render_idle_todo(profile, seat))
    if not profile.project_doc.exists():
        write_text(profile.project_doc, render_project_doc(profile))
    if not profile.tasks_doc.exists():
        write_text(profile.tasks_doc, render_tasks_doc())
    if not profile.status_doc.exists():
        write_text(profile.status_doc, render_status_doc())
    if is_managed_runtime_path(profile, profile.status_script):
        write_text(profile.status_script, render_status_wrapper(profile))
        profile.status_script.chmod(0o755)
    if is_managed_runtime_path(profile, profile.patrol_script):
        write_text(profile.patrol_script, render_patrol_wrapper(profile))
        profile.patrol_script.chmod(0o755)
    _patch_claude_settings_from_profile(profile, all_seats)
    for seat in profile.heartbeat_seats:
        # Skip heartbeat manifest/md for seats that don't run in tmux — the
        # generated docs describe a tmux-only patrol transport (status_script,
        # patrol_script, send_script) that cannot reach an openclaw frontstage.
        if not profile.seat_runs_in_tmux(seat):
            continue
        ensure_dir(profile.workspace_for(seat))
        write_text(heartbeat_md_path(profile, seat), render_heartbeat_md(profile, seat))
        write_text(heartbeat_manifest_path(profile, seat), render_heartbeat_manifest(profile, seat))
