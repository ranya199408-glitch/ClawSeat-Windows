from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from agent_admin_crud_base import (
    HOME,
    REPO_ROOT,
    CrudHooks,
    _copy_project_tool_seed,
    _normalize_project_tool_seed_names,
    _project_tool_root_path,
    _project_tool_seed_entries,
    _render_dynamic_profile,
    archive_session_artifacts,
)


class ProjectCrud:
    def __init__(self, hooks: CrudHooks) -> None:
        self.hooks = hooks

    def _home(self) -> Path:
        module = sys.modules.get("agent_admin_crud")
        return getattr(module, "HOME", HOME) if module is not None else HOME

    def _archive_session_artifacts(self, session: Any) -> None:
        archive_session_artifacts(self.hooks, session)

    def project_open(self, args: Any) -> int:
        return self.hooks.show_project(args)

    def project_create(self, args: Any) -> int:
        project_name = self.hooks.normalize_name(args.project)
        path = self.hooks.project_path(project_name)
        if path.exists():
            print(project_name)
            return 0
        repo_root_value = (args.repo_root or "").strip()
        repo_root = str(Path(repo_root_value or os.getcwd()).expanduser())
        template_name = str(getattr(args, "template", "") or "clawseat-engineering")
        template = self.hooks.load_template(template_name)
        merged = self.hooks.merge_template_local(
            template,
            {
                "project_name": project_name,
                "repo_root": repo_root,
            },
        )
        engineer_ids = [
            self.hooks.normalize_name(str(item.get("id", "")))
            for item in merged["engineers"]
            if str(item.get("id", "")).strip()
        ]
        seat_roles = {
            self.hooks.normalize_name(str(item.get("id", ""))): str(item.get("role", "") or item.get("id", ""))
            for item in merged["engineers"]
            if str(item.get("id", "")).strip()
        }
        project = self.hooks.project_cls(
            name=project_name,
            repo_root=merged["repo_root"],
            monitor_session=f"project-{project_name}-monitor",
            engineers=list(engineer_ids),
            monitor_engineers=list(engineer_ids),
            template_name=str(template.get("template_name", template_name)),
            declared_skills=list(merged.get("declared_skills", [])),
            seat_overrides={seat_id: {} for seat_id in engineer_ids},
            window_mode=getattr(args, "window_mode", None) or str(merged["window_mode"]),
            monitor_max_panes=int(merged["monitor_max_panes"]) or len(engineer_ids),
            open_detail_windows=bool(args.open_detail_windows) or bool(merged["open_detail_windows"]),
        )
        self.hooks.write_project(project)
        print(
            "hint: For a complete project setup (workspace + secrets + skills), use:\n"
            f"  bash ~/ClawSeat/scripts/install.sh --project {project.name}\n"
            "agent_admin project create is a low-level primitive; install.sh is the canonical entry.",
            file=sys.stderr,
        )
        profile_path = self._home() / ".agents" / "profiles" / f"{project_name}-profile-dynamic.toml"
        if not profile_path.exists():
            profile_template = (REPO_ROOT / "core" / "templates" / "profile-dynamic.template.toml").read_text(
                encoding="utf-8"
            )
            self.hooks.write_text(
                profile_path,
                _render_dynamic_profile(
                    profile_template,
                    project=project_name,
                    repo_root=project.repo_root,
                    profile_path=profile_path,
                    seats=engineer_ids,
                    seat_roles=seat_roles,
                ),
                None,
            )
        self.hooks.set_current_project(project.name)
        print(project.name)
        return 0

    def project_use(self, args: Any) -> int:
        project = self.hooks.load_project(args.project)
        self.hooks.set_current_project(project.name)
        print(project.name)
        return 0

    def project_current(self, args: Any) -> int:
        project_name = self.hooks.get_current_project_name()
        if not project_name:
            raise self.hooks.error_cls("No current project configured")
        print(project_name)
        return 0

    def project_layout_set(self, args: Any) -> int:
        project = self.hooks.load_project_or_current(args.project)
        if args.window_mode:
            project.window_mode = args.window_mode
        if args.monitor_max_panes is not None:
            project.monitor_max_panes = max(1, int(args.monitor_max_panes))
        if args.open_detail_windows is not None:
            project.open_detail_windows = args.open_detail_windows == "true"
        if args.monitor_engineers is not None:
            monitor_engineers = [
                self.hooks.normalize_name(item)
                for item in args.monitor_engineers.split(",")
                if item.strip()
            ]
            project.monitor_engineers = monitor_engineers
            self.hooks.write_project(project)
        print(project.name)
        return 0

    def project_init_tools(self, args: Any) -> int:
        from project_binding import load_binding, write_binding
        from real_home import real_user_home

        project = self.hooks.load_project_or_current(args.project)
        binding = load_binding(project.name)
        if binding is None:
            raise self.hooks.error_cls(
                f"project {project.name!r} has no PROJECT_BINDING.toml; bind it first before init-tools"
            )

        tools = _normalize_project_tool_seed_names(getattr(args, "tools", None))
        target_root = _project_tool_root_path(project.name)
        source_project = (getattr(args, "source_project", "") or "").strip()
        source_root = (
            _project_tool_root_path(source_project)
            if source_project
            else real_user_home()
        )
        from_mode = (getattr(args, "from_source", "real-home") or "real-home").strip()

        if binding.tools_isolation != "per-project":
            binding.tools_isolation = "per-project"

        if getattr(args, "dry_run", False):
            print(
                f"dry-run\tproject init-tools {project.name} -> {target_root}"
                f"\n  from\t{source_project or from_mode}"
                f"\n  tools\t{', '.join(tools)}"
            )
            return 0

        target_root.mkdir(parents=True, exist_ok=True)
        planned: list[str] = []
        for tool in tools:
            for rel_path, is_dir in _project_tool_seed_entries(tool):
                dst = target_root / rel_path
                if from_mode == "empty" and not source_project:
                    if is_dir:
                        dst.mkdir(parents=True, exist_ok=True)
                    else:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                    planned.append(rel_path)
                    continue
                src = source_root / rel_path
                if not src.exists():
                    continue
                _copy_project_tool_seed(src, dst)
                planned.append(rel_path)

        write_binding(binding)
        reseeded: list[str] = []
        for engineer_id in list(project.engineers):
            try:
                session = self.hooks.resolve_engineer_session(engineer_id, project_name=project.name)
                updated = self.hooks.session_service.reseed_sandbox_user_tool_dirs(session)
            except Exception as exc:  # noqa: BLE001 - surface clear operator error
                raise self.hooks.error_cls(
                    f"init-tools reseed failed for {engineer_id}: {exc}"
                ) from exc
            if updated:
                reseeded.append(f"{engineer_id}: {', '.join(updated)}")

        print(f"project init-tools updated: {project.name} [{target_root}]")
        if planned:
            print(f"seeded\t{', '.join(planned)}")
        if reseeded:
            print("\n".join(f"reseeded\t{item}" for item in reseeded))
        return 0

    def project_switch_identity(self, args: Any) -> int:
        """Record project-local identity metadata and reseed existing seats.

        Behavioral contract:
        - This command only updates PROJECT_BINDING.toml and reseeds seat sandboxes.
        - It does not call native login CLIs such as `lark-cli auth ...`.
        - It does not migrate credential payloads such as
          `.gemini/oauth_creds.json` or `.codex/auth.json`.
        - Operators must prepare the per-project tool root first
          (`project init-tools --from real-home|empty [--source-project ...]`)
          and place the desired credentials there before switching.
        """
        from project_binding import load_binding, write_binding

        project = self.hooks.load_project_or_current(args.project)
        binding = load_binding(project.name)
        if binding is None:
            raise self.hooks.error_cls(
                f"project {project.name!r} has no PROJECT_BINDING.toml; bind it first before switch-identity"
            )

        tool = str(getattr(args, "tool", "")).strip().lower()
        identity = str(getattr(args, "identity", "")).strip()
        if not identity:
            raise self.hooks.error_cls("switch-identity requires --identity")
        if tool not in {"feishu", "gemini", "codex"}:
            raise self.hooks.error_cls("switch-identity tool must be feishu, gemini, or codex")

        if tool == "feishu":
            binding.feishu_sender_app_id = identity
            binding.feishu_bot_account = identity
        elif tool == "gemini":
            binding.gemini_account_email = identity
        elif tool == "codex":
            binding.codex_account_email = identity
        binding.tools_isolation = "per-project"

        if getattr(args, "dry_run", False):
            print(
                f"dry-run\tproject switch-identity {project.name}"
                f"\n  tool\t{tool}"
                f"\n  identity\t{identity}"
                f"\n  binding\ttools_isolation=per-project"
            )
            return 0

        write_binding(binding)

        reseeded: list[str] = []
        for engineer_id in list(project.engineers):
            try:
                session = self.hooks.resolve_engineer_session(engineer_id, project_name=project.name)
                updated = self.hooks.session_service.reseed_sandbox_user_tool_dirs(session)
            except Exception as exc:  # noqa: BLE001 - surface clear operator error
                raise self.hooks.error_cls(
                    f"switch-identity reseed failed for {engineer_id}: {exc}"
                ) from exc
            if updated:
                reseeded.append(f"{engineer_id}: {', '.join(updated)}")

        print(
            f"project switch-identity updated: {project.name} tool={tool} identity={identity}"
        )
        if reseeded:
            print("\n".join(f"reseeded\t{item}" for item in reseeded))
        return 0

    def project_delete(self, args: Any) -> int:
        project = self.hooks.load_project(args.project)
        for engineer_id in list(project.engineers):
            session = self.hooks.resolve_engineer_session(engineer_id, project_name=project.name)
            self.hooks.session_service.stop_engineer(session)
            self._archive_session_artifacts(session)
            remaining_sessions = [
                item for item in self.hooks.load_sessions().values() if item.engineer_id == session.engineer_id
            ]
            if not remaining_sessions:
                self.hooks.archive_if_exists(self.hooks.engineer_path(session.engineer_id).parent, "engineers")
        sessions_dir = self.hooks.sessions_root / project.name
        if sessions_dir.exists():
            shutil.rmtree(sessions_dir)
        workspaces_dir = self.hooks.workspaces_root / project.name
        if workspaces_dir.exists():
            shutil.rmtree(workspaces_dir)
        project_dir = self.hooks.project_path(project.name).parent
        if project_dir.exists():
            shutil.rmtree(project_dir)
        current_project = self.hooks.get_current_project_name()
        if current_project == project.name:
            remaining = self.hooks.load_projects()
            next_project = sorted(remaining)[0] if remaining else None
            if next_project:
                self.hooks.set_current_project(next_project)
            elif self.hooks.current_project_path.exists():
                self.hooks.current_project_path.unlink()
        return 0
