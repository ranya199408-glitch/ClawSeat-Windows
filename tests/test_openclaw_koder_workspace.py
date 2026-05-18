from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


_REPO = Path(__file__).resolve().parents[1]
_HARNESS_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
_INSTALL_SCRIPTS = _REPO / "core" / "skills" / "clawseat-install" / "scripts"

for _path in (str(_HARNESS_SCRIPTS), str(_INSTALL_SCRIPTS), str(_REPO)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import init_koder
import migrate_profile
import render_console
import start_seat
import bootstrap_harness
from _common import load_profile
from core.scripts.agent_admin_store import StoreHandlers, StoreHooks


def _write_profile(tmp_path: Path) -> Path:
    profile_path = tmp_path / "install-profile.toml"
    tasks_root = tmp_path / "tasks" / "install"
    workspace_root = tmp_path / "workspaces" / "install"
    handoff_dir = tasks_root / "patrol" / "handoffs"
    profile_path.write_text(
        "\n".join(
            [
                'version = 1',
                'profile_name = "install-openclaw-test"',
                'template_name = "gstack-harness"',
                'project_name = "install"',
                f'repo_root = "{_REPO}"',
                f'tasks_root = "{tasks_root}"',
                f'project_doc = "{tasks_root / "PROJECT.md"}"',
                f'tasks_doc = "{tasks_root / "TASKS.md"}"',
                f'status_doc = "{tasks_root / "STATUS.md"}"',
                f'send_script = "{_REPO / "core" / "shell-scripts" / "send-and-verify.sh"}"',
                f'status_script = "{tasks_root / "patrol" / "check-status.sh"}"',
                f'patrol_script = "{tasks_root / "patrol" / "patrol-supervisor.sh"}"',
                f'agent_admin = "{_REPO / "core" / "scripts" / "agent_admin.py"}"',
                f'workspace_root = "{workspace_root}"',
                f'handoff_dir = "{handoff_dir}"',
                'heartbeat_owner = "koder"',
                'heartbeat_transport = "openclaw"',
                'active_loop_owner = "planner"',
                'default_notify_target = "planner"',
                f'heartbeat_receipt = "{workspace_root / "koder" / "HEARTBEAT_RECEIPT.toml"}"',
                'seats = ["koder", "planner", "reviewer-1"]',
                'heartbeat_seats = ["koder"]',
                '',
                '[seat_roles]',
                'koder = "frontstage-supervisor"',
                'planner = "planner-dispatcher"',
                'reviewer-1 = "reviewer"',
                '',
                '[dynamic_roster]',
                'enabled = true',
                f'session_root = "{tmp_path / "sessions"}"',
                'materialized_seats = ["koder", "planner", "reviewer-1"]',
                'runtime_seats = ["planner", "reviewer-1"]',
                'bootstrap_seats = ["koder"]',
                'default_start_seats = ["planner"]',
                'compat_legacy_seats = false',
                '',
            ]
        ),
        encoding="utf-8",
    )
    return profile_path


def _store_handlers(tmp_path: Path) -> StoreHandlers:
    return StoreHandlers(
        StoreHooks(
            error_cls=RuntimeError,
            project_cls=SimpleNamespace,
            engineer_cls=SimpleNamespace,
            session_record_cls=SimpleNamespace,
            projects_root=tmp_path / "projects",
            engineers_root=tmp_path / "engineers",
            sessions_root=tmp_path / "sessions",
            workspaces_root=tmp_path / "workspaces",
            current_project_path=tmp_path / "state" / "current_project",
            templates_root=tmp_path / "templates",
            repo_templates_root=tmp_path / "repo-templates",
            tool_binaries={},
            default_tool_args={},
            normalize_name=lambda value: value,
            ensure_dir=lambda path: path.mkdir(parents=True, exist_ok=True),
            write_text=lambda *args, **kwargs: None,
            load_toml=lambda path: {},
            q=lambda value: repr(value),
            q_array=lambda values: repr(values),
            identity_name=lambda *args, **kwargs: "identity",
            runtime_dir_for_identity=lambda *args, **kwargs: tmp_path / "runtime",
            secret_file_for=lambda *args, **kwargs: tmp_path / "secret.env",
            session_name_for=lambda *args, **kwargs: "session-name",
        )
    )


def test_init_koder_builds_workspace_from_profile_backend_seats(tmp_path):
    profile_path = _write_profile(tmp_path)
    profile = load_profile(profile_path)

    files = init_koder.build_workspace_files(
        project="install",
        profile_path=profile_path,
        profile=profile,
        feishu_group_id="",
    )

    identity = files["IDENTITY.md"]
    memory = files["MEMORY.md"]
    user = files["USER.md"]
    contract = files["WORKSPACE_CONTRACT.toml"]

    assert sorted(files) == ["IDENTITY.md", "MEMORY.md", "USER.md", "WORKSPACE_CONTRACT.toml"]
    assert "OUTBOUND" in identity
    assert "Only backend seats may be started from this workspace: `planner`, `reviewer-1`" in identity
    assert "detail_level" in user

    # MEMORY.md no longer embeds the seat roster; it points at the contract.
    assert "`WORKSPACE_CONTRACT.toml`" in memory
    assert "- `builder-1`" not in memory
    # The stale hardcoded status lines are gone.
    assert "bootstrap: pending" not in memory

    assert 'seats = ["koder", "planner", "reviewer-1"]' in contract
    assert 'runtime_seats = ["planner", "reviewer-1"]' in contract
    assert 'backend_seats = ["planner", "reviewer-1"]' in contract
    assert 'transport = "openclaw"' in contract
    assert 'heartbeat_transport = "openclaw"' in contract
    # D1: contract fingerprint lands in every contract now.
    assert 'contract_fingerprint = "' in contract
    assert 'default_backend_start_seats = ["planner"]' in contract
    assert profile.materialized_seats == ["koder", "planner", "reviewer-1"]
    assert profile.runtime_seats == ["planner", "reviewer-1"]
    assert profile.bootstrap_seats == ["koder"]


def test_make_local_override_separates_materialized_and_bootstrap_seats(tmp_path):
    profile_path = _write_profile(tmp_path)
    profile = load_profile(profile_path)

    local_override = init_koder.REPO_ROOT / "core" / "skills" / "gstack-harness" / "scripts" / "_common.py"
    assert local_override.exists()

    from _common import make_local_override

    local_path = make_local_override(profile, project_name="install", repo_root=_REPO)
    try:
        payload = local_path.read_text(encoding="utf-8")
    finally:
        local_path.unlink(missing_ok=True)

    assert 'seat_order = ["koder", "planner", "reviewer-1"]' in payload
    assert 'materialized_seats = ["koder", "planner", "reviewer-1"]' in payload
    assert 'runtime_seats = ["planner", "reviewer-1"]' in payload
    assert 'bootstrap_seats = ["koder"]' in payload
    assert 'default_start_seats = ["planner"]' in payload
    assert 'heartbeat_transport = "openclaw"' in payload


def test_load_profile_defaults_materialized_seats_to_declared_roster(tmp_path):
    profile_path = tmp_path / "starter-profile.toml"
    profile_path.write_text(
        "\n".join(
            [
                'version = 1',
                'profile_name = "starter-openclaw-test"',
                'template_name = "gstack-harness"',
                'project_name = "starter"',
                f'repo_root = "{_REPO}"',
                f'tasks_root = "{tmp_path / "tasks" / "starter"}"',
                f'project_doc = "{tmp_path / "tasks" / "starter" / "PROJECT.md"}"',
                f'tasks_doc = "{tmp_path / "tasks" / "starter" / "TASKS.md"}"',
                f'status_doc = "{tmp_path / "tasks" / "starter" / "STATUS.md"}"',
                f'send_script = "{_REPO / "core" / "shell-scripts" / "send-and-verify.sh"}"',
                f'status_script = "{tmp_path / "tasks" / "starter" / "patrol" / "check-status.sh"}"',
                f'patrol_script = "{tmp_path / "tasks" / "starter" / "patrol" / "patrol-supervisor.sh"}"',
                f'agent_admin = "{_REPO / "core" / "scripts" / "agent_admin.py"}"',
                f'workspace_root = "{tmp_path / "workspaces" / "starter"}"',
                f'handoff_dir = "{tmp_path / "tasks" / "starter" / "patrol" / "handoffs"}"',
                'heartbeat_owner = "koder"',
                'heartbeat_transport = "openclaw"',
                'active_loop_owner = "planner"',
                'default_notify_target = "planner"',
                f'heartbeat_receipt = "{tmp_path / "workspaces" / "starter" / "koder" / "HEARTBEAT_RECEIPT.toml"}"',
                'seats = ["koder", "planner"]',
                'heartbeat_seats = ["koder"]',
                '',
                '[seat_roles]',
                'koder = "frontstage-supervisor"',
                'planner = "planner-dispatcher"',
                '',
                '[dynamic_roster]',
                'enabled = true',
                f'session_root = "{tmp_path / "sessions"}"',
                'runtime_seats = ["planner"]',
                'bootstrap_seats = ["koder"]',
                'default_start_seats = ["planner"]',
                'compat_legacy_seats = false',
                '',
            ]
        ),
        encoding="utf-8",
    )

    profile = load_profile(profile_path)

    assert profile.materialized_seats == ["koder", "planner"]
    assert profile.runtime_seats == ["planner"]
    assert profile.bootstrap_seats == ["koder"]
    assert profile.default_start_seats == ["planner"]


def test_migrate_profile_emits_materialized_seats(tmp_path):
    source = {
        "profile_name": "legacy",
        "description": "legacy profile",
        "send_script": "/tmp/send.sh",
        "agent_admin": "/tmp/agent_admin.py",
        "heartbeat_owner": "koder",
        "active_loop_owner": "planner",
        "default_notify_target": "planner",
        "seats": ["koder", "planner", "builder-1"],
        "seat_roles": {
            "koder": "frontstage-supervisor",
            "planner": "planner-dispatcher",
            "builder-1": "builder",
        },
    }

    lines = migrate_profile.build_lines(
        source,
        project_name="install",
        repo_root=str(_REPO),
        bootstrap_only=False,
    )
    text = "\n".join(lines)

    assert 'seats = ["planner", "builder-1"]' in text
    assert 'materialized_seats = ["planner", "builder-1"]' in text
    assert 'bootstrap_seats = []' in text
    assert ".openclaw/koder/install-HEARTBEAT_RECEIPT.toml" in text


def test_render_console_seat_sets_exposes_runtime_collections():
    profile = SimpleNamespace(
        seats=["koder", "planner", "reviewer-1"],
        materialized_seats=["koder", "planner", "reviewer-1"],
        runtime_seats=["planner", "reviewer-1"],
        bootstrap_seats=["koder"],
        default_start_seats=["planner"],
        heartbeat_owner="koder",
    )

    sets = render_console.seat_sets(profile)

    assert sets == {
        "roster": ["koder", "planner", "reviewer-1"],
        "materialized": ["koder", "planner", "reviewer-1"],
        "runtime": ["planner", "reviewer-1"],
        "bootstrap": ["koder"],
        "default_start": ["planner"],
        "backend": ["planner", "reviewer-1"],
    }


def test_merge_template_local_materializes_declared_roster_without_bootstrap_filter(tmp_path):
    handlers = _store_handlers(tmp_path)
    template = {
        "defaults": {},
        "engineers": [
            {"id": "koder", "tool": "claude", "auth_mode": "oauth", "provider": "anthropic"},
            {"id": "planner", "tool": "claude", "auth_mode": "oauth", "provider": "anthropic"},
            {"id": "reviewer-1", "tool": "codex", "auth_mode": "api", "provider": "xcode-best"},
        ],
    }
    local = {
        "project_name": "install",
        "repo_root": str(_REPO),
        "seat_order": ["koder", "planner", "reviewer-1"],
        "materialized_seats": ["koder", "planner", "reviewer-1"],
        "bootstrap_seats": ["koder"],
    }

    merged = handlers.merge_template_local(template, local)

    assert [engineer["id"] for engineer in merged["engineers"]] == ["koder", "planner", "reviewer-1"]


def test_merge_template_local_allows_full_seat_order_with_subset_materialization(tmp_path):
    handlers = _store_handlers(tmp_path)
    template = {
        "defaults": {},
        "engineers": [
            {"id": "koder", "tool": "claude", "auth_mode": "oauth", "provider": "anthropic"},
            {"id": "planner", "tool": "claude", "auth_mode": "oauth", "provider": "anthropic"},
            {"id": "reviewer-1", "tool": "codex", "auth_mode": "api", "provider": "xcode-best"},
        ],
    }
    local = {
        "project_name": "install",
        "repo_root": str(_REPO),
        "seat_order": ["koder", "planner", "reviewer-1"],
        "materialized_seats": ["koder", "planner"],
        "bootstrap_seats": ["koder"],
    }

    merged = handlers.merge_template_local(template, local)

    assert [engineer["id"] for engineer in merged["engineers"]] == ["koder", "planner"]


def test_merge_template_local_prefers_runtime_seats_for_session_engineers(tmp_path):
    handlers = _store_handlers(tmp_path)
    template = {
        "defaults": {},
        "engineers": [
            {"id": "koder", "tool": "claude", "auth_mode": "oauth", "provider": "anthropic"},
            {"id": "memory", "tool": "claude", "auth_mode": "oauth", "provider": "anthropic"},
            {"id": "planner", "tool": "claude", "auth_mode": "oauth", "provider": "anthropic"},
        ],
    }
    local = {
        "project_name": "install",
        "repo_root": str(_REPO),
        "seat_order": ["koder", "memory", "planner"],
        "materialized_seats": ["koder", "memory", "planner"],
        "runtime_seats": ["memory", "planner"],
        "bootstrap_seats": ["koder"],
    }

    merged = handlers.merge_template_local(template, local)

    assert [engineer["id"] for engineer in merged["engineers"]] == ["memory", "planner"]


def test_find_openclaw_frontstage_contract_only_matches_openclaw_workspace(tmp_path, monkeypatch):
    openclaw_home = tmp_path / ".openclaw"
    workspace = openclaw_home / "workspace-koder"
    workspace.mkdir(parents=True, exist_ok=True)
    contract = workspace / "WORKSPACE_CONTRACT.toml"
    contract.write_text(
        "\n".join(
            [
                'version = 1',
                'seat_id = "koder"',
                'project = "install"',
                '',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(start_seat, "OPENCLAW_HOME", openclaw_home)
    profile = SimpleNamespace(project_name="install", heartbeat_owner="koder")

    detected = start_seat.find_openclaw_frontstage_contract(profile, "koder", cwd=workspace)

    assert detected == contract.resolve()

    local_workspace = tmp_path / ".agents" / "workspaces" / "install" / "koder"
    local_workspace.mkdir(parents=True, exist_ok=True)
    (local_workspace / "WORKSPACE_CONTRACT.toml").write_text(contract.read_text(encoding="utf-8"), encoding="utf-8")

    not_detected = start_seat.find_openclaw_frontstage_contract(profile, "koder", cwd=local_workspace)

    assert not_detected is None


def test_start_seat_main_blocks_openclaw_frontstage_self_start(monkeypatch, capsys):
    args = SimpleNamespace(
        profile="/tmp/install-profile.toml",
        seat="koder",
        reset=False,
        confirm_start=False,
        tool=None,
        auth_mode=None,
        provider=None,
    )
    profile = SimpleNamespace(
        project_name="install",
        heartbeat_owner="koder",
        heartbeat_transport="openclaw",
        runtime_seats=["planner"],
        default_start_seats=["planner"],
        heartbeat_seats=["koder"],
        seat_roles={"koder": "frontstage-supervisor"},
    )

    monkeypatch.setattr(start_seat, "parse_args", lambda: args)
    monkeypatch.setattr(start_seat, "load_profile", lambda path: profile)
    monkeypatch.setattr(start_seat, "materialize_profile_runtime", lambda loaded_profile: None)
    monkeypatch.setattr(
        start_seat,
        "find_openclaw_frontstage_contract",
        lambda loaded_profile, seat, cwd=None: Path("/tmp/.openclaw/workspace-koder/WORKSPACE_CONTRACT.toml"),
    )

    rc = start_seat.main()
    out = capsys.readouterr().out

    assert rc == 1
    assert "openclaw_frontstage_start_blocked" in out
    assert "start a backend seat instead" in out
    assert "'planner'" in out


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_bootstrap_harness_start_skips_openclaw_frontstage_tmux_start(monkeypatch, tmp_path, capsys):
    local_override = tmp_path / "local.toml"
    local_override.write_text("version = 1\n", encoding="utf-8")
    profile = SimpleNamespace(
        profile_path=tmp_path / "profile.toml",
        profile_name="install-openclaw-test",
        template_name="gstack-harness",
        project_name="install",
        repo_root=_REPO,
        agent_admin=_REPO / "core" / "scripts" / "agent.py",
        tasks_root=tmp_path / "tasks",
        handoff_dir=tmp_path / "tasks" / "patrol" / "handoffs",
        workspace_root=tmp_path / "workspaces" / "install",
        heartbeat_owner="koder",
        heartbeat_transport="openclaw",
        active_loop_owner="planner",
        default_notify_target="planner",
        heartbeat_receipt=tmp_path / "workspaces" / "install" / "koder" / "HEARTBEAT_RECEIPT.toml",
        seats=["koder", "planner"],
        runtime_seats=["planner"],
        heartbeat_seats=["koder"],
        seat_roles={"koder": "frontstage-supervisor", "planner": "planner-dispatcher"},
        seat_overrides={},
        dynamic_roster_enabled=True,
        session_root=tmp_path / "sessions",
        materialized_seats=["koder", "planner"],
        bootstrap_seats=["koder"],
        default_start_seats=["planner"],
        compat_legacy_seats=False,
        legacy_seats=[],
        legacy_seat_roles={},
    )
    args = SimpleNamespace(
        profile=str(profile.profile_path),
        project_name=None,
        repo_root=None,
        start=True,
        refresh_existing=False,
        link_tasks=False,
        no_workspace_sync=True,
        strict_workspace_sync=False,
    )
    commands: list[list[str]] = []

    def fake_run_command(cmd, cwd=None):
        commands.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(bootstrap_harness, "parse_args", lambda: args)
    monkeypatch.setattr(bootstrap_harness, "load_profile", lambda _: profile)
    monkeypatch.setattr(bootstrap_harness, "with_overrides", lambda profile, project_name, repo_root: profile)
    monkeypatch.setattr(bootstrap_harness, "make_local_override", lambda profile, project_name, repo_root: local_override)
    monkeypatch.setattr(bootstrap_harness, "run_command", fake_run_command)
    monkeypatch.setattr(bootstrap_harness, "require_success", lambda result, context: None)
    monkeypatch.setattr(bootstrap_harness, "materialize_profile_runtime", lambda _: None)
    monkeypatch.setattr(bootstrap_harness, "_link_sandbox_tasks_to_real_home", lambda *args, **kwargs: None)
    monkeypatch.setattr(bootstrap_harness, "_sync_workspaces_host_to_sandbox", lambda *args, **kwargs: None)
    monkeypatch.setattr(bootstrap_harness, "seed_empty_secret_from_peer", lambda *args, **kwargs: None)
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", "/tmp/fake-home")

    rc = bootstrap_harness.main()

    assert rc == 0
    out = capsys.readouterr().out
    assert "start_skipped" in out
    assert not any("start-engineer" in " ".join(cmd) for cmd in commands)
