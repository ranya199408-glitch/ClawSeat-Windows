from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


REPO = Path(__file__).resolve().parents[1]
for path in (
    REPO,
    REPO / "core" / "lib",
    REPO / "core" / "scripts",
    REPO / "core" / "skills" / "clawseat-install" / "scripts",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import init_koder
import projects_registry
from core.lib.machine_config import load_machine
from core.scripts.bootstrap_machine_tenants import bootstrap_machine_tenants

_DECISION_PAYLOAD = REPO / "core" / "skills" / "memory-oracle" / "scripts" / "decision_payload.py"
_spec = importlib.util.spec_from_file_location("decision_payload", _DECISION_PAYLOAD)
assert _spec and _spec.loader
decision_payload = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(decision_payload)


def _valid_payload() -> dict:
    return {
        "decision_id": "123e4567-e89b-12d3-a456-426614174000",
        "from_seat": "install-memory",
        "to_seat": "install-koder",
        "severity": "HIGH",
        "category": "scope",
        "context": "需要 operator 选择下一步。",
        "options": [
            {"id": "A", "label": "继续", "impact": "保持当前方向"},
            {"id": "B", "label": "暂停", "impact": "等待更多信息"},
        ],
        "default_if_timeout": "A",
        "timeout_minutes": 60,
        "created_at": "2026-04-28T00:00:00Z",
    }


def test_koder_skill_v2_has_stable_sections() -> None:
    text = (REPO / "core" / "skills" / "clawseat-koder" / "SKILL.md").read_text(encoding="utf-8")
    assert "status: stable" in text
    assert text.count("\n## ") >= 9
    assert "Human Readability Rules" in text


def test_frontstage_skill_and_hygiene_template_removed() -> None:
    old_skill = REPO / "core" / "skills" / ("clawseat-koder" + "-frontstage")
    assert not old_skill.exists()
    assert not (REPO / "core" / "templates" / "shared" / "TOOLS" / "koder-hygiene.md").exists()


def test_projects_registry_derives_seats_for_legacy_entry() -> None:
    entry = projects_registry.ProjectEntry.from_dict(
        {"name": "install", "primary_seat": "memory", "tmux_name": "install-memory"}
    )
    assert entry.seats == {"memory": "install-memory"}


def test_projects_registry_round_trips_explicit_seats(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    created = projects_registry.register_project(
        "install",
        "memory",
        seats={"memory": "install-memory", "planner": "install-planner-claude"},
    )
    assert created.seats["planner"] == "install-planner-claude"
    loaded = projects_registry.get_project("install")
    assert loaded is not None
    assert loaded.seats == {
        "memory": "install-memory",
        "planner": "install-planner-claude",
    }


def test_machine_bootstrap_adds_feishu_routing_from_contract(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    memory_root = tmp_path / "memory"
    workspace = tmp_path / "openclaw" / "workspace-koder"
    workspace.mkdir(parents=True)
    (workspace / "WORKSPACE_CONTRACT.toml").write_text(
        'project = "install"\nfeishu_group_id = "<FEISHU_GROUP_ID>"\n',
        encoding="utf-8",
    )
    scan_dir = memory_root / "machine"
    scan_dir.mkdir(parents=True)
    (scan_dir / "openclaw.json").write_text(
        json.dumps({"agents": [{"name": "koder", "workspace": str(workspace)}]}),
        encoding="utf-8",
    )

    assert bootstrap_machine_tenants(memory_root) == 0
    cfg = load_machine(tmp_path / ".clawseat" / "machine.toml")
    assert cfg.feishu_routing["<FEISHU_GROUP_ID>"].bound_projects == ["install"]
    assert cfg.feishu_routing["<FEISHU_GROUP_ID>"].default_project == "install"


def test_init_koder_workspace_is_four_files(tmp_path) -> None:
    profile = SimpleNamespace(
        heartbeat_owner="koder",
        heartbeat_transport="openclaw",
        active_loop_owner="planner",
        default_notify_target="planner",
        seats=["koder", "planner"],
        runtime_seats=["planner"],
        default_start_seats=["planner"],
        seat_overrides={},
        seat_roles={"koder": "frontstage-supervisor", "planner": "planner-dispatcher"},
    )
    files = init_koder.build_workspace_files(
        project="install",
        profile_path=tmp_path / "profile.toml",
        profile=profile,
        feishu_group_id="",
        workspace_path=tmp_path / "workspace-koder",
    )
    assert sorted(files) == ["IDENTITY.md", "MEMORY.md", "USER.md", "WORKSPACE_CONTRACT.toml"]
    assert "OUTBOUND" in files["IDENTITY.md"]
    assert 'feishu_group_id = "<FEISHU_GROUP_ID>"' in files["WORKSPACE_CONTRACT.toml"]


def test_profile_dynamic_template_excludes_koder_bootstrap() -> None:
    text = (REPO / "core" / "templates" / "profile-dynamic.template.toml").read_text(encoding="utf-8")
    assert "bootstrap_seats = []" in text
    assert "heartbeat_receipt = \"{{heartbeat_receipt}}\"" in text
    assert "koder" not in text


def test_socratic_references_split_to_memory_report_mode() -> None:
    socratic_refs = {path.name for path in (REPO / "core" / "skills" / "clawseat-intake" / "references").iterdir()}
    report_refs = {path.name for path in (REPO / "core" / "skills" / "memory-report-mode" / "references").iterdir()}
    assert {"shared-tone.md", "glossary-global.toml", "i18n.md", "capability-catalog.yaml"} <= socratic_refs
    assert {"drift-signals.md", "report-mode.md", "tui-card-format.md", "north-star-schema.toml"} <= report_refs


def test_memory_oracle_declares_dual_skill_loading() -> None:
    text = (REPO / "core" / "skills" / "memory-oracle" / "SKILL.md").read_text(encoding="utf-8")
    assert "clawseat-intake" in text
    assert "memory-report-mode" in text
    assert "decision_payload.py send" in text


def test_decision_payload_validates_and_sends(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = decision_payload.tmux_send_payload("install-koder", _valid_payload(), runner=fake_run)

    assert result.returncode == 0
    assert calls[0][0:2] == ["tmux-send", "install-koder"]
    assert calls[0][2].startswith("DECISION_PAYLOAD ")


def test_decision_payload_rejects_invalid_default() -> None:
    payload = _valid_payload()
    payload["default_if_timeout"] = "C"
    try:
        decision_payload.validate_decision_payload(payload)
    except decision_payload.DecisionPayloadError as exc:
        assert "default_if_timeout" in str(exc)
    else:
        raise AssertionError("invalid default_if_timeout must fail")
