from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


def current_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def copy_workspace_overlay(src: Path, dst: Path, ensure_dir: Callable[[Path], None]) -> None:
    if not src.exists():
        return
    allow_names = {
        ".claude",
        ".mcp.json",
        ".mcp-data",
        "CLAUDE.md",
        "AGENTS.md",
        "GEMINI.md",
        "skills",
        "SESSION_ID",
        "COMMANDS.md",
        "WORKSPACE.md",
        "BACKEND_HARDENING_NEXT.md",
    }
    for item in src.iterdir():
        if item.name == ".git":
            continue
        if item.name not in allow_names:
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            ensure_dir(target.parent)
            shutil.copy2(item, target)


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(
            "tmp",
            "log",
            "*.sqlite-wal",
            "*.sqlite-shm",
            ".DS_Store",
        ),
    )


@dataclass
class LegacyHooks:
    legacy_root: Path
    engineers_root: Path
    legacy_gemini_sandboxes: list[Path]
    project_defaults: dict[str, dict[str, Any]]
    legacy_engineers: dict[str, dict[str, Any]]
    error_cls: type[Exception]
    project_cls: type
    engineer_cls: type
    session_record_cls: type
    tool_binaries: dict[str, str]
    ensure_root_layout: Callable[[], None]
    ensure_dir: Callable[[Path], None]
    project_path: Callable[[str], Path]
    load_toml: Callable[[Path], dict]
    load_projects: Callable[[], dict[str, Any]]
    write_project: Callable[[Any], None]
    write_engineer: Callable[[Any], None]
    write_session: Callable[[Any], None]
    apply_template: Callable[[Any, Any], None]
    create_engineer_profile: Callable[..., Any]
    create_session_record: Callable[..., Any]
    write_env_file: Callable[..., None]
    write_text: Callable[..., None]
    ensure_secret_permissions: Callable[[Path], None]


class LegacyHandlers:
    def __init__(self, hooks: LegacyHooks) -> None:
        self.hooks = hooks

    def archive_path(self, category: str, name: str) -> Path:
        return self.hooks.legacy_root / category / f"{name}-{current_timestamp()}"

    def archive_if_exists(self, path: Path, category: str) -> None:
        if not path.exists():
            return
        target = self.archive_path(category, path.name)
        self.hooks.ensure_dir(target.parent)
        shutil.move(str(path), str(target))

    def migrate_session_model(self) -> None:
        projects = self.hooks.load_projects()
        if not projects:
            return
        for path in sorted(self.hooks.engineers_root.glob("*/engineer.toml")):
            data = self.hooks.load_toml(path)
            engineer_id = data["id"]
            if "project" not in data:
                continue

            project_name = data["project"]
            if project_name not in projects:
                continue
            project = projects[project_name]

            profile = self.hooks.engineer_cls(
                engineer_id=engineer_id,
                display_name=data.get("display_name", engineer_id),
                aliases=list(data.get("aliases", [])),
                role=data.get("role", engineer_id),
                role_details=list(data.get("role_details", [])),
                skills=list(data.get("skills", [])),
                human_facing=bool(data.get("human_facing", False)),
                active_loop_owner=bool(data.get("active_loop_owner", False)),
                dispatch_authority=bool(data.get("dispatch_authority", False)),
                patrol_authority=bool(data.get("patrol_authority", False)),
                unblock_authority=bool(data.get("unblock_authority", False)),
                escalation_authority=bool(data.get("escalation_authority", False)),
                remind_active_loop_owner=bool(data.get("remind_active_loop_owner", False)),
                review_authority=bool(data.get("review_authority", False)),
                design_authority=bool(data.get("design_authority", False)),
                default_tool=data.get("tool", ""),
                default_auth_mode=data.get("auth_mode", ""),
                default_provider=data.get("provider", ""),
            )
            session = self.hooks.session_record_cls(
                engineer_id=engineer_id,
                project=project_name,
                tool=data["tool"],
                auth_mode=data["auth_mode"],
                provider=data["provider"],
                identity=data["identity"],
                workspace=data["workspace"],
                runtime_dir=data["runtime_dir"],
                session=data["session"],
                bin_path=data.get("bin_path", self.hooks.tool_binaries[data["tool"]]),
                monitor=bool(data.get("monitor", True)),
                legacy_sessions=list(data.get("legacy_sessions", [])),
                launch_args=list(data.get("launch_args", [])),
                secret_file=data.get("secret_file", ""),
                wrapper=data.get("wrapper", ""),
            )
            self.hooks.write_engineer(profile)
            self.hooks.write_session(session)
            self.hooks.apply_template(session, project)

    def migrate_legacy(self, args: Any) -> int:
        self.hooks.ensure_root_layout()

        for name, defaults in self.hooks.project_defaults.items():
            path = self.hooks.project_path(name)
            if path.exists() and not args.force:
                continue
            project = self.hooks.project_cls(
                name=name,
                repo_root=defaults["repo_root"],
                monitor_session=defaults["monitor_session"],
                engineers=list(defaults["engineers"]),
                monitor_engineers=list(defaults["monitor_engineers"]),
                template_name="",
                seat_overrides={},
            )
            self.hooks.write_project(project)

        projects = self.hooks.load_projects()
        coding = projects["coding"]

        for engineer_id, legacy in self.hooks.legacy_engineers.items():
            profile = self.hooks.create_engineer_profile(
                engineer_id=engineer_id,
                tool=legacy["tool"],
                auth_mode=legacy["auth_mode"],
                provider=legacy["provider"],
            )
            record = self.hooks.create_session_record(
                engineer_id=engineer_id,
                project=coding,
                tool=legacy["tool"],
                auth_mode=legacy["auth_mode"],
                provider=legacy["provider"],
                monitor=bool(legacy["monitor"]),
                legacy_session=legacy["legacy_session"],
                launch_args=list(legacy.get("launch_args", [])),
                wrapper=legacy.get("wrapper", ""),
            )

            self.hooks.write_engineer(profile)
            self.hooks.write_session(record)
            self.hooks.apply_template(record, coding)
            legacy_workspace_value = legacy.get("legacy_workspace", "")
            if legacy_workspace_value:
                copy_workspace_overlay(Path(legacy_workspace_value), Path(record.workspace), self.hooks.ensure_dir)

            # OAuth runtime is user-managed via the TUI — never seed OAuth
            # tokens/auth.json from a shared legacy identity. The runtime dir is
            # still created so the seat has a sandbox HOME to write into once
            # the user logs in via the CLI's first-run flow.
            # (API mode: credential files are seeded below via record.secret_file
            # + seed_secret; that remains correct.)
            runtime_dir = Path(record.runtime_dir)
            if legacy.get("auth_mode") == "oauth":
                self.hooks.ensure_dir(runtime_dir)
            else:
                seed_runtime = Path(legacy["seed_runtime"]) if legacy.get("seed_runtime") else None
                if seed_runtime and seed_runtime.exists() and (args.force or not runtime_dir.exists()):
                    copy_tree(seed_runtime, runtime_dir)
                else:
                    self.hooks.ensure_dir(runtime_dir)

            if record.secret_file:
                seed_secret = Path(legacy["seed_secret"])
                secret_path = Path(record.secret_file)
                if seed_secret.exists():
                    self.hooks.ensure_dir(secret_path.parent)
                    shutil.copy2(seed_secret, secret_path)
                else:
                    self.hooks.write_env_file(secret_path, {}, self.hooks.ensure_dir, self.hooks.write_text)
                self.hooks.ensure_secret_permissions(secret_path)

        for sandbox in self.hooks.legacy_gemini_sandboxes:
            if sandbox.exists():
                target = self.hooks.legacy_root / "gemini-sandboxes" / sandbox.name
                self.hooks.ensure_dir(target.parent)
                if target.exists():
                    target = self.hooks.legacy_root / "gemini-sandboxes" / f"{sandbox.name}-{current_timestamp()}"
                shutil.move(str(sandbox), str(target))

        return 0
