from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from agent_admin_crud_base import HOME, REPO_ROOT, CrudHooks, _render_dynamic_profile


class BootstrapCrud:
    def __init__(self, hooks: CrudHooks) -> None:
        self.hooks = hooks

    def _home(self) -> Path:
        module = sys.modules.get("agent_admin_crud")
        return getattr(module, "HOME", HOME) if module is not None else HOME

    def project_bootstrap(self, args: Any) -> int:
        template = self.hooks.load_template(args.template)
        local_path = Path(args.local).expanduser()
        if not local_path.exists():
            raise self.hooks.error_cls(f"Local config not found: {local_path}")
        if local_path.is_dir():
            raise self.hooks.error_cls(
                f"Local config must be a TOML file, not a directory: {local_path}"
            )
        local = self.hooks.load_toml(local_path)
        merged = self.hooks.merge_template_local(template, local)
        local_seat_overrides = {
            self.hooks.normalize_name(str(item.get("id", ""))): {
                str(key): value
                for key, value in dict(item).items()
                if key != "id"
            }
            for item in local.get("overrides", [])
            if str(item.get("id", "")).strip()
        }

        project_name = merged["project_name"]
        path = self.hooks.project_path(project_name)
        if path.exists():
            raise self.hooks.error_cls(f"{project_name} already exists")

        project = self.hooks.project_cls(
            name=project_name,
            repo_root=merged["repo_root"],
            monitor_session=f"project-{project_name}-monitor",
            engineers=[],
            monitor_engineers=[],
            template_name=str(template.get("template_name", args.template)),
            declared_skills=list(merged.get("declared_skills", [])),
            seat_overrides=local_seat_overrides,
            window_mode=merged["window_mode"],
            monitor_max_panes=merged["monitor_max_panes"],
            open_detail_windows=merged["open_detail_windows"],
        )
        self.hooks.write_project(project)

        template_profiles: dict[str, Any] = {}
        engineer_order: list[str] = []
        for engineer_spec in merged["engineers"]:
            engineer_id = self.hooks.normalize_name(str(engineer_spec["id"]))
            engineer_order.append(engineer_id)
            if self.hooks.engineer_path(engineer_id).exists():
                base_profile = self.hooks.load_engineer(engineer_id)
            else:
                role = str(engineer_spec.get("role", "")).strip()
                base_profile = self.hooks.create_engineer_profile(
                    engineer_id=engineer_id,
                    tool=str(engineer_spec["tool"]),
                    auth_mode=str(engineer_spec["auth_mode"]),
                    provider=str(engineer_spec["provider"]),
                    role=role,
                    display_name=str(engineer_spec.get("display_name", "")).strip() or role or engineer_id,
                    role_details=list(engineer_spec.get("role_details", [])),
                    skills=list(engineer_spec.get("skills", [])),
                    aliases=list(engineer_spec.get("aliases", [])),
                    human_facing=bool(engineer_spec.get("human_facing", False)),
                    active_loop_owner=bool(engineer_spec.get("active_loop_owner", False)),
                    dispatch_authority=bool(engineer_spec.get("dispatch_authority", False)),
                    patrol_authority=bool(engineer_spec.get("patrol_authority", False)),
                    unblock_authority=bool(engineer_spec.get("unblock_authority", False)),
                    escalation_authority=bool(engineer_spec.get("escalation_authority", False)),
                    remind_active_loop_owner=bool(engineer_spec.get("remind_active_loop_owner", False)),
                    review_authority=bool(engineer_spec.get("review_authority", False)),
                    design_authority=bool(engineer_spec.get("design_authority", False)),
                )
            template_profiles[engineer_id] = self.hooks.merge_engineer_profile_with_template(base_profile, engineer_spec)

        created_sessions: list[Any] = []
        for engineer_spec in merged["engineers"]:
            engineer_id = self.hooks.normalize_name(str(engineer_spec["id"]))
            if self.hooks.session_path(project.name, engineer_id).exists():
                raise self.hooks.error_cls(f"{engineer_id} already has a session in {project.name}")
            if self.hooks.engineer_path(engineer_id).exists():
                profile = self.hooks.load_engineer(engineer_id)
            else:
                profile = template_profiles[engineer_id]
                self.hooks.write_engineer(profile)
            template_profile = template_profiles[engineer_id]

            session = self.hooks.create_session_record(
                engineer_id=engineer_id,
                project=project,
                tool=str(engineer_spec["tool"]),
                auth_mode=str(engineer_spec["auth_mode"]),
                provider=str(engineer_spec["provider"]),
                monitor=bool(engineer_spec.get("monitor", True)),
                session_name=str(engineer_spec.get("session_name", "")).strip(),
            )
            # Attach template-only fields (model, effort) for settings generation.
            # These are not part of SessionRecord but are consumed by _render_claude_settings.
            session._template_model = str(engineer_spec.get("model", "")).strip()
            session._template_effort = str(engineer_spec.get("effort", "")).strip()
            self.hooks.write_session(session)
            self.hooks.apply_template(
                session,
                project,
                engineer_override=template_profile,
                optional_skills=list(merged.get("optional_skills", [])),
                project_engineers=template_profiles,
                engineer_order=engineer_order,
            )
            self.hooks.ensure_dir(Path(session.runtime_dir))
            if session.secret_file:
                self.hooks.ensure_empty_env_file(Path(session.secret_file), self.hooks.ensure_dir, self.hooks.write_text)
            if session.engineer_id not in project.engineers:
                project.engineers.append(session.engineer_id)
            if session.monitor and session.engineer_id not in project.monitor_engineers:
                project.monitor_engineers.append(session.engineer_id)
            created_sessions.append(session)

        self.hooks.write_project(project)
        profile_path = self._home() / ".agents" / "profiles" / f"{project.name}-profile-dynamic.toml"
        if not profile_path.exists():
            profile_template = (REPO_ROOT / "core" / "templates" / "profile-dynamic.template.toml").read_text(
                encoding="utf-8"
            )
            seat_roles = {
                self.hooks.normalize_name(str(item.get("id", ""))): str(item.get("role", "") or item.get("id", ""))
                for item in merged["engineers"]
                if str(item.get("id", "")).strip()
            }
            self.hooks.write_text(
                profile_path,
                _render_dynamic_profile(
                    profile_template,
                    project=project.name,
                    repo_root=project.repo_root,
                    profile_path=profile_path,
                    seats=engineer_order,
                    seat_roles=seat_roles,
                ),
                None,
            )
        self.hooks.set_current_project(project.name)

        print(f"bootstrapped {project.name}")
        print(f"repo_root\t{project.repo_root}")
        for session in created_sessions:
            print(
                "\t".join(
                    [
                        session.engineer_id,
                        session.session,
                        session.tool,
                        session.auth_mode,
                        session.provider,
                    ]
                )
            )
        if any(session.auth_mode == "api" for session in created_sessions):
            print("warning\tapi secrets not provisioned — provision before starting sessions")
        if args.start:
            self.hooks.session_service.start_project(project)
            start_ids = self.hooks.session_service.project_autostart_engineer_ids(project)
            print(f"started\t{','.join(start_ids)}")
        return 0
