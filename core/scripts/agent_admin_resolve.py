from __future__ import annotations

import os
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_CORE_LIB = _REPO_ROOT / "core" / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))
from core.lib.real_home import real_user_home
from core.lib.runtime_home_links import ensure_runtime_home_links
from project_binding import load_binding
from project_tool_root import project_tool_root


@dataclass
class ResolveHooks:
    error_cls: type[Exception]
    default_tool_args: dict[str, list[str]]
    codex_api_provider_configs: dict[str, dict[str, Any]]
    common_env: Callable[[], dict[str, str]]
    ensure_dir: Callable[[Path], None]
    parse_env_file: Callable[[Path], dict[str, str]]
    write_codex_api_config: Callable[[Any, Path, Path, dict[str, dict[str, Any]], Any], None]
    write_text: Callable[[Path, str, int | None], None]
    load_project: Callable[[str], Any]
    load_projects: Callable[[], dict[str, Any]]
    load_engineers: Callable[[], dict[str, Any]]
    load_sessions: Callable[[], dict[tuple[str, str], Any]]
    get_current_project_name: Callable[[dict[str, Any] | None], str | None]
    display_name_for: Callable[[Any | None, str], str]


class ResolveHandlers:
    def __init__(self, hooks: ResolveHooks) -> None:
        self.hooks = hooks

    def build_runtime(self, session: Any) -> tuple[str, dict[str, str]]:
        runtime_dir = Path(session.runtime_dir)
        tool = session.tool
        mode = session.auth_mode
        binary = session.bin_path
        env = self.hooks.common_env()
        shared_agent_home = Path(os.environ.get("AGENT_HOME", str(real_user_home()))).expanduser()
        binding = load_binding(session.project)
        tools_isolation = binding.tools_isolation if binding is not None else "shared-real-home"

        home = runtime_dir / "home"
        xdg_config = runtime_dir / "xdg" / "config"
        xdg_data = runtime_dir / "xdg" / "data"
        xdg_cache = runtime_dir / "xdg" / "cache"
        xdg_state = runtime_dir / "xdg" / "state"
        for path in (home, xdg_config, xdg_data, xdg_cache, xdg_state):
            self.hooks.ensure_dir(path)
        # C4: auto-provision runtime HOME symlinks so the seat sees
        # ~/.lark-cli and ~/.openclaw without manual post-boot fixup.
        # Idempotent; skips silently when a real dir already occupies
        # the sandbox target.
        link_result = ensure_runtime_home_links(home, shared_agent_home)
        for action in link_result.actions:
            if action.status in ("created", "fixed"):
                print(
                    f"runtime_home_link {action.status}: {action.sandbox_path} -> {action.target}",
                    file=sys.stderr,
                )
            elif action.status == "error":
                print(
                    f"runtime_home_link error: {action.name} — {action.detail}",
                    file=sys.stderr,
                )
        env.update(
            {
                "AGENT_HOME": str(shared_agent_home),
                "AGENTS_ROOT": str(shared_agent_home / ".agents"),
                "CLAWSEAT_PROJECT": session.project,
                "CLAWSEAT_TOOLS_ISOLATION": tools_isolation,
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(xdg_config),
                "XDG_DATA_HOME": str(xdg_data),
                "XDG_CACHE_HOME": str(xdg_cache),
                "XDG_STATE_HOME": str(xdg_state),
            }
        )
        if tools_isolation == "per-project":
            env["CLAWSEAT_PROJECT_TOOL_ROOT"] = str(project_tool_root(session.project, home=shared_agent_home))

        codex_home = None
        if tool == "codex":
            codex_home = runtime_dir / "codex"
            self.hooks.ensure_dir(codex_home)
            self.hooks.ensure_dir(codex_home / "tmp")
            env["CODEX_HOME"] = str(codex_home)

        if mode == "api":
            if not session.secret_file:
                session_path = (
                    self.hooks.sessions_root
                    / session.project
                    / session.engineer_id
                    / "session.toml"
                )
                raise self.hooks.error_cls(
                    f"{session.engineer_id} is missing 'secret_file' in session.toml "
                    f"(auth_mode=api requires it). "
                    f"Edit {session_path} and add:\n"
                    f"  secret_file = \"/path/to/{session.engineer_id}.env\"\n"
                    f"Or run: agent-admin session switch-harness "
                    f"--engineer {session.engineer_id} "
                    f"--project {session.project} "
                    f"--tool {session.tool} --mode api --provider {session.provider}"
                )
            secret_env = self.hooks.parse_env_file(Path(session.secret_file))
            env.update(secret_env)
            if tool == "claude" and session.provider == "anthropic-console":
                # A1: Direct Anthropic Console API key (scoped-role=Claude Code).
                # Does not override base_url — uses default api.anthropic.com.
                api_key = secret_env.get("ANTHROPIC_API_KEY", "").strip()
                if not api_key:
                    raise self.hooks.error_cls(
                        f"{session.engineer_id} anthropic-console requires "
                        f"ANTHROPIC_API_KEY in {session.secret_file}. "
                        "Create a Claude Code scoped API key in Anthropic Console."
                    )
                env["ANTHROPIC_API_KEY"] = api_key
                for stale in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN"):
                    env.pop(stale, None)
            elif tool == "codex":
                api_key = secret_env.get("OPENAI_API_KEY", "")
                if not api_key:
                    raise self.hooks.error_cls(
                        f"{session.engineer_id} is missing OPENAI_API_KEY in {session.secret_file}"
                    )
                auth_path = codex_home / "auth.json"
                # Atomic 0o600 create: O_EXCL refuses to follow an attacker-
                # planted symlink, and the mode is applied at creation so the
                # key is never briefly world-readable under a loose umask.
                auth_payload = json.dumps(
                    {"OPENAI_API_KEY": api_key}, ensure_ascii=True
                ).encode("ascii")
                if auth_path.exists() or auth_path.is_symlink():
                    auth_path.unlink()
                fd = os.open(
                    auth_path,
                    os.O_CREAT | os.O_WRONLY | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                try:
                    os.write(fd, auth_payload)
                finally:
                    os.close(fd)
                self.hooks.write_codex_api_config(
                    session,
                    codex_home,
                    Path(self.hooks.load_project(session.project).repo_root),
                    self.hooks.codex_api_provider_configs,
                    self.hooks.write_text,
                )
                env.pop("OPENAI_API_KEY", None)

        # C5: CLAUDE_CODE_OAUTH_TOKEN long-lived token (bypasses Keychain).
        # Secret file must contain `CLAUDE_CODE_OAUTH_TOKEN=<CLAUDE_CODE_OAUTH_TOKEN>`
        # (obtained via `claude setup-token`). Works only for tool=claude.
        if mode == "oauth_token":
            if tool != "claude":
                raise self.hooks.error_cls(
                    f"auth_mode=oauth_token is only supported for tool=claude "
                    f"(got tool={tool!r}). Use tool=claude with `claude setup-token` "
                    "to obtain the 1-year token."
                )
            if not session.secret_file:
                raise self.hooks.error_cls(
                    f"{session.engineer_id} is missing 'secret_file' in session.toml "
                    "(auth_mode=oauth_token requires it). The file must contain "
                    "CLAUDE_CODE_OAUTH_TOKEN=<CLAUDE_CODE_OAUTH_TOKEN> (from `claude setup-token`)."
                )
            secret_env = self.hooks.parse_env_file(Path(session.secret_file))
            token = secret_env.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
            if not token:
                raise self.hooks.error_cls(
                    f"{session.engineer_id} secret_file={session.secret_file} "
                    "is missing CLAUDE_CODE_OAUTH_TOKEN. Run `claude setup-token` "
                    "on the operator host and paste the token into that file."
                )
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
            # Defensive: drop any ambient ANTHROPIC_API_KEY / AUTH_TOKEN /
            # BASE_URL so they don't shadow the oauth-token codepath.
            for stale in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
                env.pop(stale, None)

        # C5: Claude Code Router (CCR) — point Claude Code at a local
        # proxy that multiplexes providers. Needs no secret file (CCR
        # holds all upstream keys in ~/.claude-code-router/config.json).
        if mode == "ccr":
            if tool != "claude":
                raise self.hooks.error_cls(
                    f"auth_mode=ccr is only supported for tool=claude "
                    f"(got tool={tool!r}). Start `ccr start` and point "
                    "this seat at it."
                )
            from agent_admin_config import DEFAULT_CCR_BASE_URL
            ccr_base_url = (
                os.environ.get("CLAWSEAT_CCR_BASE_URL")
                or DEFAULT_CCR_BASE_URL
            )
            env["ANTHROPIC_BASE_URL"] = ccr_base_url
            # CCR accepts any non-empty token; keep the value obviously
            # fake so a leaked log is not mistaken for a real key.
            env["ANTHROPIC_AUTH_TOKEN"] = "ccr-local-dummy"
            # Clear any stale OAuth credentials path to ensure CC uses the env.
            for stale in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
                env.pop(stale, None)

        # Shared skill-level secrets (audit finding #6, 2026-05-11):
        # ClawSeat's secret_file is auth-tied (auth_mode=api/oauth_token only).
        # Skills like cartooner-image / cartooner-audio / cartooner-video etc.
        # need provider keys (MINIMAX_API_KEY, etc.) regardless of the seat's
        # auth mode. Without injection, builder-image (codex/oauth/chatgpt)
        # had no MINIMAX_API_KEY in sandbox env and was forced to source the
        # cartooner repo's .env as a workaround — sandbox isolation breach.
        #
        # Convention: any .env file under ~/.agents/secrets/shared/ is
        # sourced into every seat's sandbox env. Operators put skill-level
        # provider keys there once; all seats inherit. Override path via
        # CLAWSEAT_SHARED_SECRETS_DIR.
        shared_secrets_dir = Path(
            os.environ.get("CLAWSEAT_SHARED_SECRETS_DIR")
            or shared_agent_home / ".agents" / "secrets" / "shared"
        )
        if shared_secrets_dir.is_dir():
            for env_file in sorted(shared_secrets_dir.glob("*.env")):
                try:
                    shared_env = self.hooks.parse_env_file(env_file)
                except Exception:
                    continue
                for key, value in shared_env.items():
                    if key not in env:  # auth-tied keys win over shared
                        env[key] = value

        return binary, env

    def default_launch_args(self, session: Any) -> list[str]:
        return list(self.hooks.default_tool_args.get(session.tool, []))

    def resolve_engineer(self, name: str, engineers: dict[str, Any] | None = None) -> Any:
        engineer_map = engineers or self.hooks.load_engineers()
        if name in engineer_map:
            return engineer_map[name]
        for engineer in engineer_map.values():
            if name in engineer.aliases:
                return engineer
        raise self.hooks.error_cls(f"Unknown engineer: {name}")

    def resolve_engineer_session(
        self,
        engineer_name: str,
        project_name: str | None = None,
        sessions: dict[tuple[str, str], Any] | None = None,
        engineers: dict[str, Any] | None = None,
    ) -> Any:
        engineer = self.resolve_engineer(engineer_name, engineers)
        session_map = sessions or self.hooks.load_sessions()
        if project_name:
            key = (project_name, engineer.engineer_id)
            if key in session_map:
                return session_map[key]
            raise self.hooks.error_cls(f"{engineer.engineer_id} has no session in project {project_name}")

        current_project = self.hooks.get_current_project_name(self.hooks.load_projects())
        if current_project and (current_project, engineer.engineer_id) in session_map:
            return session_map[(current_project, engineer.engineer_id)]
        matches = [session for session in session_map.values() if session.engineer_id == engineer.engineer_id]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise self.hooks.error_cls(f"{engineer.engineer_id} has no session")
        raise self.hooks.error_cls(f"{engineer.engineer_id} exists in multiple projects; specify --project")

    def resolve_session(
        self,
        name: str,
        project_name: str | None = None,
        *,
        prefer_current_project: bool = True,
    ) -> str:
        engineers = self.hooks.load_engineers()
        sessions = self.hooks.load_sessions()
        engineer_error: Exception | None = None
        try:
            if project_name:
                session = self.resolve_engineer_session(
                    name,
                    project_name=project_name,
                    sessions=sessions,
                    engineers=engineers,
                )
            elif prefer_current_project:
                session = self.resolve_engineer_session(name, sessions=sessions, engineers=engineers)
            else:
                engineer = self.resolve_engineer(name, engineers)
                matches = [session for session in sessions.values() if session.engineer_id == engineer.engineer_id]
                if len(matches) == 1:
                    session = matches[0]
                elif not matches:
                    raise self.hooks.error_cls(f"{engineer.engineer_id} has no session")
                else:
                    raise self.hooks.error_cls(
                        f"{engineer.engineer_id} exists in multiple projects; specify --project"
                    )
            return session.session
        except self.hooks.error_cls as exc:
            engineer_error = exc
        for session in sessions.values():
            if name == session.session or name in session.legacy_sessions:
                return session.session
        projects = self.hooks.load_projects()
        if name in projects:
            return projects[name].monitor_session
        for project in projects.values():
            if name == project.monitor_session:
                return project.monitor_session
        if engineer_error is not None:
            raise engineer_error
        raise self.hooks.error_cls(f"Unknown session or engineer: {name}")

    def display_label(self, engineer: Any | None, fallback: str) -> str:
        display_name = self.hooks.display_name_for(engineer, fallback)
        if display_name == fallback:
            return fallback
        return f"{display_name} ({fallback})"
