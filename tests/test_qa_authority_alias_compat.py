from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from agent_admin_store import StoreHandlers, StoreHooks  # noqa: E402


@dataclass
class _Engineer:
    engineer_id: str
    display_name: str
    aliases: list[str] = field(default_factory=list)
    role: str = ""
    role_details: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    human_facing: bool = False
    active_loop_owner: bool = False
    dispatch_authority: bool = False
    patrol_authority: bool = False
    unblock_authority: bool = False
    escalation_authority: bool = False
    remind_active_loop_owner: bool = False
    review_authority: bool = False
    design_authority: bool = False
    default_tool: str = ""
    default_auth_mode: str = ""
    default_provider: str = ""


def _handlers(tmp_path: Path, profile_data: dict) -> StoreHandlers:
    def _load_profile_toml(_path: Path) -> dict:
        return dict(profile_data)

    hooks = StoreHooks(
        error_cls=RuntimeError,
        project_cls=SimpleNamespace,
        engineer_cls=_Engineer,
        session_record_cls=SimpleNamespace,
        projects_root=tmp_path / "projects",
        engineers_root=tmp_path / "engineers",
        sessions_root=tmp_path / "sessions",
        workspaces_root=tmp_path / "workspaces",
        current_project_path=tmp_path / "current",
        templates_root=tmp_path / "templates",
        repo_templates_root=tmp_path / "repo-templates",
        tool_binaries={},
        default_tool_args={},
        normalize_name=lambda value: value,
        ensure_dir=lambda path: path.mkdir(parents=True, exist_ok=True),
        write_text=lambda path, text, mode=None: path.write_text(text, encoding="utf-8"),
        load_toml=_load_profile_toml,
        q=lambda value: repr(value),
        q_array=lambda values: repr(values),
        identity_name=lambda *args, **kwargs: "identity",
        runtime_dir_for_identity=lambda *args, **kwargs: tmp_path / "runtime",
        secret_file_for=lambda *args, **kwargs: tmp_path / "secret.env",
        session_name_for=lambda project, engineer, tool: f"{project}-{engineer}-{tool}",
    )
    return StoreHandlers(hooks)


def test_patrol_authority_ignores_removed_legacy_alias(tmp_path: Path) -> None:
    """The removed legacy authority field no longer grants patrol authority."""
    common = {"id": "patrol", "display_name": "Patrol"}

    old_only = _handlers(tmp_path, {**common, "qa_authority": True}).load_engineer("patrol")
    assert old_only.patrol_authority is False

    new_profile = _handlers(tmp_path, {**common, "patrol_authority": True}).load_engineer("patrol")
    assert new_profile.patrol_authority is True

    both = _handlers(tmp_path, {**common, "qa_authority": True, "patrol_authority": False}).load_engineer("patrol")
    assert both.patrol_authority is False
