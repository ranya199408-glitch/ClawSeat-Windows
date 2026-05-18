#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
ENGINE_ROOT = SCRIPT_PATH.parent
REPO_ROOT = ENGINE_ROOT.parent.parent
DEFAULT_TEMPLATE_ROOT = REPO_ROOT / "core" / "templates"
GENERATED_ROOT = ENGINE_ROOT / "generated"
AGENT_ADMIN_SCRIPTS = REPO_ROOT / "core" / "scripts"

if str(AGENT_ADMIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(AGENT_ADMIN_SCRIPTS))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from core.lib.utils import load_toml, q, q_array  # noqa: E402
from core.lib.real_home import real_user_home

import agent_admin_runtime
from agent_admin_config import (
    CODEX_API_PROVIDER_CONFIGS,
    DEFAULT_TOOL_ARGS,
    TOOL_BINARIES,
    validate_runtime_combo,
)
from agent_admin_runtime import (
    ensure_empty_env_file,
    identity_name,
    runtime_dir_for_identity,
    secret_file_for,
    session_name_for,
    write_codex_api_config,
)


REPLICATED_PATTERN = re.compile(r"^\{role\}-\{n\}$")
SUPPORTED_TEMPLATE_VERSION = 1
# SESSIONS_ROOT: use SESSIONS_ROOT env var or default to ~/.agents/sessions
_SESSIONS_ROOT_DEFAULT = str(real_user_home() / ".agents" / "sessions")
SESSIONS_ROOT = Path(os.environ.get("SESSIONS_ROOT", _SESSIONS_ROOT_DEFAULT))

DEFAULT_PROJECT_SCOPED_FIELDS = [
    "defaults.workspace_template",
    "defaults.tasks_root_template",
    "paths.secret_path_template",
    "paths.runtime_identity_template",
    "paths.session_name_template",
    "paths.session_path_template",
]


@dataclass
class SeatTemplate:
    source_path: Path
    version: int
    template_id: str
    role: str
    tool: str
    provider: str
    capabilities: list[str]
    instance_mode: str
    instance_id_pattern: str
    auth_mode: str
    workspace_template: str
    tasks_root_template: str
    monitor: bool
    optional: bool
    secret_path_template: str
    runtime_identity_template: str
    session_name_template: str
    session_path_template: str
    skills: list[str]
    dispatch_target_role: str
    reply_to_role: str
    require_project_scope: bool
    project_scoped_fields: list[str]


@dataclass
class SeatInstance:
    template: SeatTemplate
    project_name: str
    repo_root: Path
    instance_id: str
    replica_index: int | None
    workspace: Path
    tasks_root: Path
    runtime_identity: str
    runtime_dir: Path
    session_name: str
    session_path: Path
    secret_path: Path
    bin_path: str
    launch_args: list[str]
    tmux_config_path: Path
    manifest_path: Path
    contract_path: Path
    workspace_guide_path: Path
    tool_guide_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Instantiate a single seat from a refactor template.")
    parser.add_argument("--template-id", required=True, help="Seat template id, for example builder.")
    parser.add_argument("--project-name", required=True, help="Target project name.")
    parser.add_argument("--instance-id", help="Explicit instance id. Optional for auto-allocation.")
    parser.add_argument(
        "--repo-root",
        help="Repo root used for project-local template overrides. Defaults to this repo.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite generated files if they already exist.")
    parser.add_argument("--dry-run", action="store_true", help="Resolve and validate without writing files.")
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str, mode: int | None = None) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)


def template_search_roots(repo_root: Path) -> list[Path]:
    return [
        repo_root / ".agents" / "templates" / "seats",
        real_user_home() / ".agents" / "templates" / "seats",
        DEFAULT_TEMPLATE_ROOT,
    ]


def resolve_template_path(template_id: str, repo_root: Path) -> Path:
    filename = template_id if template_id.endswith(".toml") else f"{template_id}.toml"
    for root in template_search_roots(repo_root):
        candidate = root / filename
        if candidate.exists():
            return candidate
    roots = ", ".join(str(root) for root in template_search_roots(repo_root))
    raise SystemExit(f"template {filename} not found; searched {roots}")


def require_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"template missing required string field: {key}")
    return value.strip()


def require_bool(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise SystemExit(f"template missing required bool field: {key}")
    return value


def require_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise SystemExit(f"template missing required int field: {key}")
    return value


def require_string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SystemExit(f"template missing required string list field: {key}")
    return [item.strip() for item in value if item.strip()]


def load_template(template_path: Path) -> SeatTemplate:
    data = load_toml(template_path)
    defaults = data.get("defaults")
    paths = data.get("paths")
    validation = data.get("validation", {})
    routing = data.get("routing", {})
    skills = data.get("skills", {})
    if not isinstance(defaults, dict):
        raise SystemExit("template missing required [defaults] table")
    if not isinstance(paths, dict):
        raise SystemExit("template missing required [paths] table")
    if not isinstance(validation, dict):
        raise SystemExit("template [validation] must be a table")
    if not isinstance(routing, dict):
        raise SystemExit("template [routing] must be a table")
    if not isinstance(skills, dict):
        raise SystemExit("template [skills] must be a table")

    template = SeatTemplate(
        source_path=template_path,
        version=require_int(data, "version"),
        template_id=require_string(data, "template_id"),
        role=require_string(data, "role"),
        tool=require_string(data, "tool"),
        provider=require_string(data, "provider"),
        capabilities=require_string_list(data, "capabilities"),
        instance_mode=require_string(data, "instance_mode"),
        instance_id_pattern=require_string(data, "instance_id_pattern"),
        auth_mode=require_string(defaults, "auth_mode"),
        workspace_template=require_string(defaults, "workspace_template"),
        tasks_root_template=require_string(defaults, "tasks_root_template"),
        monitor=require_bool(defaults, "monitor"),
        optional=require_bool(defaults, "optional"),
        secret_path_template=require_string(paths, "secret_path_template"),
        runtime_identity_template=require_string(paths, "runtime_identity_template"),
        session_name_template=require_string(paths, "session_name_template"),
        session_path_template=require_string(paths, "session_path_template"),
        skills=require_string_list(skills, "default") if "default" in skills else [],
        dispatch_target_role=str(routing.get("dispatch_target_role", "")).strip(),
        reply_to_role=str(routing.get("reply_to_role", "")).strip(),
        require_project_scope=bool(validation.get("require_project_scope", False)),
        project_scoped_fields=(
            require_string_list(validation, "project_scoped_fields")
            if "project_scoped_fields" in validation
            else list(DEFAULT_PROJECT_SCOPED_FIELDS)
        ),
    )
    validate_template_shape(template)
    return template


def validate_template_shape(template: SeatTemplate) -> None:
    if template.version != SUPPORTED_TEMPLATE_VERSION:
        raise SystemExit(
            f"unsupported template version {template.version} for {template.template_id}; "
            f"supported version is {SUPPORTED_TEMPLATE_VERSION}"
        )
    validate_runtime_combo(
        template.tool,
        template.auth_mode,
        template.provider,
        error_cls=SystemExit,
        context=f"template {template.template_id}",
    )
    if template.instance_mode not in {"singleton", "replicated"}:
        raise SystemExit(
            f"template {template.template_id} has invalid instance_mode {template.instance_mode!r}"
        )
    if template.instance_mode == "singleton":
        if template.instance_id_pattern != template.role:
            raise SystemExit(
                f"singleton template {template.template_id} must use literal instance_id_pattern={template.role!r}"
            )
    else:
        if not REPLICATED_PATTERN.match(template.instance_id_pattern):
            raise SystemExit(
                f"replicated template {template.template_id} must use instance_id_pattern '{{role}}-{{n}}'"
            )


def template_context(
    template: SeatTemplate,
    project_name: str,
    instance_id: str,
    replica_index: int | None,
) -> dict[str, str]:
    return {
        "project": project_name,
        "instance_id": instance_id,
        "instance": instance_id,
        "role": template.role,
        "n": "" if replica_index is None else str(replica_index),
        "tool": template.tool,
        "provider": template.provider,
        "auth_mode": template.auth_mode,
        "template_id": template.template_id,
    }


def render_template_value(value: str, context: dict[str, str], *, label: str) -> str:
    try:
        return value.format(**context)
    except KeyError as exc:
        raise SystemExit(f"unable to render {label}: missing placeholder {exc.args[0]!r}") from exc


def session_ids_for_project(project_name: str) -> list[str]:
    project_root = SESSIONS_ROOT / project_name
    if not project_root.exists():
        return []
    return sorted(path.name for path in project_root.iterdir() if path.is_dir())


def next_replica_index(project_name: str, role: str) -> int:
    pattern = re.compile(rf"^{re.escape(role)}-(\d+)$")
    highest = 0
    for seat_id in session_ids_for_project(project_name):
        match = pattern.match(seat_id)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def resolve_instance_id(
    template: SeatTemplate,
    project_name: str,
    requested_instance_id: str | None,
) -> tuple[str, int | None]:
    if template.instance_mode == "singleton":
        instance_id = template.role
        if requested_instance_id and requested_instance_id != instance_id:
            raise SystemExit(
                f"singleton template {template.template_id} must use instance_id {instance_id!r}, got {requested_instance_id!r}"
            )
        return instance_id, None

    if requested_instance_id:
        pattern = re.compile(rf"^{re.escape(template.role)}-(\d+)$")
        match = pattern.match(requested_instance_id)
        if not match:
            raise SystemExit(
                f"replicated template {template.template_id} expects instance_id like {template.role}-N, got {requested_instance_id!r}"
            )
        replica_index = int(match.group(1))
        if replica_index < 1:
            raise SystemExit(
                f"replicated template {template.template_id} requires a 1-based instance id, got {requested_instance_id!r}"
            )
        return requested_instance_id, replica_index

    replica_index = next_replica_index(project_name, template.role)
    return f"{template.role}-{replica_index}", replica_index


def validate_project_scope_template(template: SeatTemplate) -> None:
    if not template.require_project_scope:
        return
    fields = {
        "defaults.workspace_template": template.workspace_template,
        "defaults.tasks_root_template": template.tasks_root_template,
        "paths.secret_path_template": template.secret_path_template,
        "paths.runtime_identity_template": template.runtime_identity_template,
        "paths.session_name_template": template.session_name_template,
        "paths.session_path_template": template.session_path_template,
    }
    missing = [name for name in template.project_scoped_fields if "{project}" not in fields.get(name, "")]
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"template {template.template_id} is missing {{project}} in: {joined}")


def build_instance(
    template: SeatTemplate,
    project_name: str,
    repo_root: Path,
    requested_instance_id: str | None,
) -> SeatInstance:
    validate_project_scope_template(template)
    instance_id, replica_index = resolve_instance_id(template, project_name, requested_instance_id)
    context = template_context(template, project_name, instance_id, replica_index)

    workspace = Path(render_template_value(template.workspace_template, context, label="workspace_template"))
    tasks_root = Path(render_template_value(template.tasks_root_template, context, label="tasks_root_template"))
    rendered_secret = Path(
        render_template_value(template.secret_path_template, context, label="secret_path_template")
    )
    rendered_identity = render_template_value(
        template.runtime_identity_template, context, label="runtime_identity_template"
    )
    rendered_session_name = render_template_value(
        template.session_name_template, context, label="session_name_template"
    )
    rendered_session_path = Path(
        render_template_value(template.session_path_template, context, label="session_path_template")
    )

    expected_identity = identity_name(
        template.tool,
        template.auth_mode,
        template.provider,
        instance_id,
        project_name,
    )
    if rendered_identity != expected_identity:
        raise SystemExit(
            f"runtime identity mismatch: template={rendered_identity} helper={expected_identity}"
        )

    expected_session_name = session_name_for(project_name, instance_id, template.tool)
    if rendered_session_name != expected_session_name:
        raise SystemExit(
            f"session name mismatch: template={rendered_session_name} helper={expected_session_name}"
        )

    expected_session_path = SESSIONS_ROOT / project_name / instance_id / "session.toml"
    if rendered_session_path != expected_session_path:
        raise SystemExit(
            f"session path mismatch: template={rendered_session_path} canonical={expected_session_path}"
        )

    if template.auth_mode == "api":
        expected_secret = secret_file_for(template.tool, template.provider, instance_id, project_name)
        if rendered_secret != expected_secret:
            raise SystemExit(
                f"secret path mismatch: template={rendered_secret} helper={expected_secret}"
            )

    validate_project_scope_values(
        project_name=project_name,
        values={
            "workspace": str(workspace),
            "tasks_root": str(tasks_root),
            "secret_path": str(rendered_secret),
            "runtime_identity": rendered_identity,
            "session_name": rendered_session_name,
            "session_path": str(rendered_session_path),
        },
    )

    runtime_dir = runtime_dir_for_identity(template.tool, template.auth_mode, rendered_identity)
    manifest_dir = GENERATED_ROOT / project_name / instance_id
    workspace_guide_path = workspace / "WORKSPACE.md"
    contract_path = workspace / "WORKSPACE_CONTRACT.toml"
    tool_guide_name = "AGENTS.md"
    return SeatInstance(
        template=template,
        project_name=project_name,
        repo_root=repo_root,
        instance_id=instance_id,
        replica_index=replica_index,
        workspace=workspace,
        tasks_root=tasks_root,
        runtime_identity=rendered_identity,
        runtime_dir=runtime_dir,
        session_name=rendered_session_name,
        session_path=rendered_session_path,
        secret_path=rendered_secret,
        bin_path=TOOL_BINARIES[template.tool],
        launch_args=list(DEFAULT_TOOL_ARGS.get(template.tool, [])),
        tmux_config_path=workspace / "TMUX_SESSION.toml",
        manifest_path=manifest_dir / "instance.toml",
        contract_path=contract_path,
        workspace_guide_path=workspace_guide_path,
        tool_guide_path=workspace / tool_guide_name,
    )


def validate_project_scope_values(*, project_name: str, values: dict[str, str]) -> None:
    missing = [name for name, value in values.items() if project_name not in value]
    if missing:
        joined = ", ".join(sorted(missing))
        raise SystemExit(f"project-scope validation failed; missing project token in {joined}")


def render_workspace_contract(instance: SeatInstance) -> str:
    todo_path = instance.tasks_root / "TODO.md"
    project_doc = instance.repo_root / ".tasks" / "PROJECT.md"
    tasks_doc = instance.repo_root / ".tasks" / "TASKS.md"
    payload = {
        "engineer_id": instance.instance_id,
        "project": instance.project_name,
        "template_id": instance.template.template_id,
        "tool": instance.template.tool,
        "provider": instance.template.provider,
        "auth_mode": instance.template.auth_mode,
        "workspace": str(instance.workspace),
        "role": instance.template.role,
        "instance_mode": instance.template.instance_mode,
        "session_name": instance.session_name,
        "session_path": str(instance.session_path),
        "runtime_identity": instance.runtime_identity,
        "runtime_dir": str(instance.runtime_dir),
        "tasks_root": str(instance.tasks_root),
        "capabilities": list(instance.template.capabilities),
        "skills": list(instance.template.skills),
        "read_first": [str(todo_path), str(project_doc), str(tasks_doc)],
        "source_paths": [str(todo_path), str(project_doc), str(tasks_doc)],
        "reply_to_role": instance.template.reply_to_role,
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    lines = [
        "version = 1",
        f"engineer_id = {q(instance.instance_id)}",
        f"seat_id = {q(instance.instance_id)}",
        'transport = "tmux"',
        f"project = {q(instance.project_name)}",
        f"template_id = {q(instance.template.template_id)}",
        f"tool = {q(instance.template.tool)}",
        f"provider = {q(instance.template.provider)}",
        f"auth_mode = {q(instance.template.auth_mode)}",
        f"workspace = {q(str(instance.workspace))}",
        f"role = {q(instance.template.role)}",
        f"instance_mode = {q(instance.template.instance_mode)}",
        f"session_name = {q(instance.session_name)}",
        f"session_path = {q(str(instance.session_path))}",
        f"runtime_identity = {q(instance.runtime_identity)}",
        f"runtime_dir = {q(str(instance.runtime_dir))}",
        f"tasks_root = {q(str(instance.tasks_root))}",
        f"fingerprint = {q(fingerprint)}",
        f"contract_fingerprint = {q(fingerprint)}",
        f"capabilities = {q_array(instance.template.capabilities)}",
        f"skills = {q_array(instance.template.skills)}",
        f"read_first = {q_array(payload['read_first'])}",
        f"source_paths = {q_array(payload['source_paths'])}",
        f"reply_to_role = {q(instance.template.reply_to_role)}",
    ]
    if instance.template.auth_mode == "api":
        lines.append(f"secret_file = {q(str(instance.secret_path))}")
    lines.append("")
    return "\n".join(lines)


def render_workspace_notes(instance: SeatInstance) -> str:
    lines = [
        "# Workspace Notes",
        "",
        f"Template: `{instance.template.template_id}`",
        f"Project: `{instance.project_name}`",
        f"Seat: `{instance.instance_id}`",
        f"Role: `{instance.template.role}`",
        "",
        "Paths:",
        f"- repo: `{instance.repo_root}`",
        f"- tasks_root: `{instance.tasks_root}`",
        f"- session: `{instance.session_path}`",
        f"- tmux config: `{instance.tmux_config_path}`",
        "",
        "This workspace was generated by `refac/engine/instantiate_seat.py`.",
    ]
    return "\n".join(lines) + "\n"


def render_tool_guide(instance: SeatInstance) -> str:
    lines = [
        f"# {instance.instance_id}",
        "",
        f"- Tool: `{instance.template.tool}`",
        f"- Project: `{instance.project_name}`",
        f"- Repo root: `{instance.repo_root}`",
        f"- Workspace: `{instance.workspace}`",
        f"- Role: `{instance.template.role}`",
        f"- Template: `{instance.template.template_id}`",
        "",
        "## Read First",
        "",
        f"1. `{instance.tasks_root / 'TODO.md'}`",
        f"2. `{instance.repo_root / '.tasks' / 'PROJECT.md'}`",
        f"3. `{instance.repo_root / '.tasks' / 'TASKS.md'}`",
        "4. task-specific docs referenced by the current TODO",
        "",
        "## Capabilities",
        "",
    ]
    if instance.template.capabilities:
        lines.extend(f"- {capability}" for capability in instance.template.capabilities)
    else:
        lines.append("- template-defined seat responsibilities")
    lines.extend(
        [
            "",
            "## Protocol",
            "",
            "- treat `WORKSPACE_CONTRACT.toml` as the durable seat contract",
            f"- reply_to role: `{instance.template.reply_to_role or '-'}`",
            f"- dispatch target role: `{instance.template.dispatch_target_role or '-'}`",
        ]
    )
    if instance.template.skills:
        lines.extend(["", "## Loaded Skills", ""])
        lines.extend(f"- `{skill}`" for skill in instance.template.skills)
    lines.append("")
    return "\n".join(lines)


def render_session_record(instance: SeatInstance) -> str:
    lines = [
        "version = 1",
        f"project = {q(instance.project_name)}",
        f"engineer_id = {q(instance.instance_id)}",
        f"tool = {q(instance.template.tool)}",
        f"auth_mode = {q(instance.template.auth_mode)}",
        f"provider = {q(instance.template.provider)}",
        f"identity = {q(instance.runtime_identity)}",
        f"workspace = {q(str(instance.workspace))}",
        f"runtime_dir = {q(str(instance.runtime_dir))}",
        f"session = {q(instance.session_name)}",
        f"bin_path = {q(instance.bin_path)}",
        f"monitor = {'true' if instance.template.monitor else 'false'}",
        "legacy_sessions = []",
        f"launch_args = {q_array(instance.launch_args)}",
        f"template_id = {q(instance.template.template_id)}",
        f"role = {q(instance.template.role)}",
        f"instance_mode = {q(instance.template.instance_mode)}",
        f"tasks_root = {q(str(instance.tasks_root))}",
    ]
    if instance.template.auth_mode == "api":
        lines.append(f"secret_file = {q(str(instance.secret_path))}")
    lines.append("")
    return "\n".join(lines)


def render_tmux_config(instance: SeatInstance) -> str:
    # Resolve agentctl.sh relative to this file — no hardcoded maintainer path.
    _engine_dir = Path(__file__).resolve().parent  # .../ClawSeat/core/engine
    _clawseat_root = _engine_dir.parent.parent  # .../ClawSeat
    _agentctl_sh = _clawseat_root / "core" / "shell-scripts" / "agentctl.sh"
    agentctl_command = [
        str(_agentctl_sh),
        "run-engineer",
        "--project",
        instance.project_name,
        instance.instance_id,
    ]
    direct_command = [instance.bin_path, *instance.launch_args]
    lines = [
        "version = 1",
        f"project = {q(instance.project_name)}",
        f"engineer_id = {q(instance.instance_id)}",
        f"template_id = {q(instance.template.template_id)}",
        f"tool = {q(instance.template.tool)}",
        f"session_name = {q(instance.session_name)}",
        f"workspace = {q(str(instance.workspace))}",
        f"repo_root = {q(str(instance.repo_root))}",
        f"session_record = {q(str(instance.session_path))}",
        f"workspace_contract = {q(str(instance.contract_path))}",
        f"runtime_dir = {q(str(instance.runtime_dir))}",
        f"tasks_root = {q(str(instance.tasks_root))}",
        f"bin_path = {q(instance.bin_path)}",
        f"launch_args = {q_array(instance.launch_args)}",
        f"agentctl_command = {q_array(agentctl_command)}",
        f"direct_command = {q_array(direct_command)}",
        f"tmux_new_session = {q_array(['tmux', 'new-session', '-d', '-s', instance.session_name, '-c', str(instance.workspace)])}",
        "",
    ]
    return "\n".join(lines)


def render_manifest(instance: SeatInstance) -> str:
    lines = [
        "version = 1",
        f"template_id = {q(instance.template.template_id)}",
        f"template_path = {q(str(instance.template.source_path))}",
        f"project = {q(instance.project_name)}",
        f"instance_id = {q(instance.instance_id)}",
        f"instance_mode = {q(instance.template.instance_mode)}",
        f"role = {q(instance.template.role)}",
        f"workspace = {q(str(instance.workspace))}",
        f"contract_path = {q(str(instance.contract_path))}",
        f"workspace_guide_path = {q(str(instance.workspace_guide_path))}",
        f"tool_guide_path = {q(str(instance.tool_guide_path))}",
        f"session_path = {q(str(instance.session_path))}",
        f"tmux_config_path = {q(str(instance.tmux_config_path))}",
        f"runtime_dir = {q(str(instance.runtime_dir))}",
        f"tasks_root = {q(str(instance.tasks_root))}",
    ]
    if instance.template.auth_mode == "api":
        lines.append(f"secret_path = {q(str(instance.secret_path))}")
    lines.append("")
    return "\n".join(lines)


def ensure_runtime_scaffold(instance: SeatInstance) -> None:
    ensure_dir(instance.runtime_dir)
    if instance.template.auth_mode == "api":
        ensure_empty_env_file(instance.secret_path, ensure_dir, write_text)
    if instance.template.tool == "codex" and instance.template.auth_mode == "api":
        write_codex_api_config(
            type("Session", (), {"provider": instance.template.provider})(),
            instance.runtime_dir / "codex",
            instance.repo_root,
            CODEX_API_PROVIDER_CONFIGS,
            write_text,
        )


def create_repo_symlink(instance: SeatInstance) -> None:
    """Ensure `<workspace>/repos/repo` points at the seat's repo root.

    Previously this short-circuited on any pre-existing entry (symlink or
    regular file) at the link path, so `instantiate_seat --force` would
    silently keep a symlink pointing at an old repo when the user pointed
    the template at a new one (audit H10). Now:

    - if `link` is a correct symlink to `instance.repo_root`, no-op
    - if it is an incorrect symlink (points somewhere else), replace it
    - if it is a regular file or directory, refuse to overwrite — the
      caller must remove it explicitly to avoid losing user data
    """
    repos_dir = instance.workspace / "repos"
    ensure_dir(repos_dir)
    link = repos_dir / "repo"
    expected = instance.repo_root.resolve(strict=False)

    if link.is_symlink():
        try:
            current = link.resolve(strict=False)
        except OSError:
            current = None
        if current == expected:
            return
        link.unlink()
        link.symlink_to(instance.repo_root)
        return

    if link.exists():
        raise SystemExit(
            f"refusing to overwrite non-symlink at {link}; "
            f"remove it manually before re-running instantiate_seat"
        )

    link.symlink_to(instance.repo_root)


def assert_writable_targets(instance: SeatInstance, force: bool) -> None:
    targets = [
        instance.contract_path,
        instance.workspace_guide_path,
        instance.tool_guide_path,
        instance.session_path,
        instance.tmux_config_path,
        instance.manifest_path,
        instance.manifest_path.parent / "tmux-session.toml",
    ]
    existing = [path for path in targets if path.exists()]
    if existing and not force:
        joined = ", ".join(str(path) for path in existing)
        raise SystemExit(f"refusing to overwrite existing generated files without --force: {joined}")


def write_instance(instance: SeatInstance, *, force: bool) -> None:
    assert_writable_targets(instance, force)
    ensure_dir(instance.workspace)
    ensure_dir(instance.tasks_root)
    ensure_runtime_scaffold(instance)
    write_text(instance.contract_path, render_workspace_contract(instance))
    write_text(instance.workspace_guide_path, render_workspace_notes(instance))
    write_text(instance.tool_guide_path, render_tool_guide(instance))
    write_text(instance.session_path, render_session_record(instance))
    write_text(instance.tmux_config_path, render_tmux_config(instance))
    write_text(instance.manifest_path, render_manifest(instance))
    generated_tmux_path = instance.manifest_path.parent / "tmux-session.toml"
    write_text(generated_tmux_path, render_tmux_config(instance))
    create_repo_symlink(instance)


def summary(instance: SeatInstance) -> str:
    payload = {
        "template_id": instance.template.template_id,
        "template_path": str(instance.template.source_path),
        "project": instance.project_name,
        "instance_id": instance.instance_id,
        "instance_mode": instance.template.instance_mode,
        "workspace": str(instance.workspace),
        "contract_path": str(instance.contract_path),
        "session_path": str(instance.session_path),
        "tmux_config_path": str(instance.tmux_config_path),
        "manifest_path": str(instance.manifest_path),
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).expanduser() if args.repo_root else REPO_ROOT
    template_path = resolve_template_path(args.template_id, repo_root)
    template = load_template(template_path)
    if template.template_id != args.template_id:
        # Template ids are the public loader contract, so fail on drift rather than silently aliasing.
        raise SystemExit(
            f"template id mismatch: requested {args.template_id!r}, file declares {template.template_id!r}"
        )
    instance = build_instance(
        template=template,
        project_name=args.project_name,
        repo_root=repo_root,
        requested_instance_id=args.instance_id,
    )
    if args.dry_run:
        print(summary(instance))
        return 0
    write_instance(instance, force=args.force)
    print(summary(instance))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
