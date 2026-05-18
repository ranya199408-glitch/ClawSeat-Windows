"""Tests for core/tui/ancestor_brief.py — the renderer that produces the
memory bootstrap brief consumed by the ancestor seat on first boot.

Spec: docs/schemas/memory-bootstrap-brief.md (v0.1).
Scope: pure renderer + YAML envelope correctness, tmux liveness probe
mocking, idempotent rendering, CLI entrypoint smoke.

No side effects outside tmp_path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "core" / "lib"))

from core.tui import ancestor_brief  # noqa: E402


# Canonical v2 profile fragment used across tests (matches §4 spec).
SAMPLE_V2_PROFILE = """
version = 2

profile_name = "install"
template_name = "gstack-harness"
project_name = "install"
repo_root = "{CLAWSEAT_ROOT}"
tasks_root = "~/.agents/tasks/install"
project_doc = "~/.agents/tasks/install/PROJECT.md"
tasks_doc = "~/.agents/tasks/install/TASKS.md"
status_doc = "~/.agents/tasks/install/STATUS.md"
send_script = "{CLAWSEAT_ROOT}/core/shell-scripts/send-and-verify.sh"
agent_admin = "{CLAWSEAT_ROOT}/core/scripts/agent_admin.py"
workspace_root = "~/.agents/workspaces/install"
handoff_dir = "~/.agents/tasks/install/patrol/handoffs"

machine_services = ["memory"]
openclaw_frontstage_agent = "yu"

seats = ["ancestor", "planner", "builder", "reviewer", "patrol", "designer"]

[seat_roles]
ancestor = "ancestor"
planner = "planner-dispatcher"
builder = "builder"
reviewer = "reviewer"
patrol = "patrol"
designer = "designer"

[seat_overrides.ancestor]
tool = "claude"
auth_mode = "oauth_token"
provider = "anthropic"

[seat_overrides.planner]
tool = "claude"
auth_mode = "oauth_token"
provider = "anthropic"

[seat_overrides.builder]
tool = "claude"
auth_mode = "oauth_token"
provider = "anthropic"
parallel_instances = 1

[seat_overrides.reviewer]
tool = "codex"
auth_mode = "api"
provider = "xcode-best"
parallel_instances = 2

[seat_overrides.patrol]
tool = "claude"
auth_mode = "api"
provider = "minimax"
parallel_instances = 1

[seat_overrides.designer]
tool = "gemini"
auth_mode = "oauth"
provider = "google"

[dynamic_roster]
enabled = true
session_root = "~/.agents/sessions"
bootstrap_seats = ["ancestor"]
default_start_seats = ["ancestor", "planner"]

[patrol]
planner_brief_path = "~/.agents/tasks/install/planner/PLANNER_BRIEF.md"
cadence_minutes = 45

[observability]
announce_planner_events = true
announce_event_types = [
    "task.completed",
    "chain.closeout",
    "seat.blocked_on_modal",
    "seat.context_near_limit",
    "config-drift-recovery",
]
"""


@pytest.fixture
def v2_profile(tmp_path: Path) -> Path:
    p = tmp_path / "install-profile-dynamic.toml"
    p.write_text(SAMPLE_V2_PROFILE)
    return p


@pytest.fixture
def no_tmux(monkeypatch):
    """Pretend no session is alive unless a test overrides."""
    monkeypatch.setattr(ancestor_brief, "_tmux_session_alive", lambda name: False)


# ─────────────────────────────────────────────────────────────────────
# Section A — context loader
# ─────────────────────────────────────────────────────────────────────

class TestLoadContext:

    def test_basic_load(self, v2_profile, no_tmux):
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        assert ctx.project == "install"
        assert ctx.profile_version == 2
        assert ctx.openclaw_tenant == "yu"
        assert ctx.machine_services_required == ["memory"]
        assert ctx.patrol_cadence_minutes == 45  # profile override respected

    def test_all_six_seats_declared(self, v2_profile, no_tmux):
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        roles = [s.role for s in ctx.seats]
        assert roles == ["ancestor", "planner", "builder", "reviewer", "patrol", "designer"]

    def test_parallel_only_on_fan_out_seats(self, v2_profile, no_tmux):
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        by_role = {s.role: s for s in ctx.seats}
        assert by_role["builder"].parallel_instances == 1
        assert by_role["reviewer"].parallel_instances == 2
        assert by_role["patrol"].parallel_instances == 1
        # Singletons must NOT carry parallel_instances
        assert by_role["ancestor"].parallel_instances is None
        assert by_role["planner"].parallel_instances is None
        assert by_role["designer"].parallel_instances is None

    def test_session_names_follow_convention(self, v2_profile, no_tmux):
        """Singletons get `<project>-<role>-<tool>`; fan-out roles get
        `<project>-<role>-<N>-<tool>` with one entry per parallel_instances."""
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        by_role = {s.role: s for s in ctx.seats}
        # singletons
        assert by_role["ancestor"].sessions == ["install-ancestor-claude"]
        assert by_role["planner"].sessions == ["install-planner-claude"]
        assert by_role["designer"].sessions == ["install-designer-gemini"]
        # fan-out: builder has parallel_instances=1 → 1 indexed session
        assert by_role["builder"].sessions == ["install-builder-1-claude"]
        # fan-out: reviewer has parallel_instances=2 → 2 indexed sessions
        assert by_role["reviewer"].sessions == [
            "install-reviewer-1-codex", "install-reviewer-2-codex",
        ]

    def test_seats_default_to_pending_when_tmux_absent(self, v2_profile, no_tmux):
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        assert all(s.state == "pending" for s in ctx.seats)

    def test_ancestor_marked_alive_when_tmux_probe_confirms(self, v2_profile, monkeypatch):
        monkeypatch.setattr(
            ancestor_brief, "_tmux_session_alive",
            lambda name: name == "install-ancestor-claude",
        )
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        by_role = {s.role: s for s in ctx.seats}
        assert by_role["ancestor"].state == "alive"
        assert by_role["planner"].state == "pending"

    def test_fan_out_state_is_alive_only_if_all_sessions_alive(self, v2_profile, monkeypatch):
        """reviewer has 2 sessions; if only 1 is alive, state must stay 'pending'."""
        monkeypatch.setattr(
            ancestor_brief, "_tmux_session_alive",
            lambda name: name == "install-reviewer-1-codex",  # only index 1 alive
        )
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        by_role = {s.role: s for s in ctx.seats}
        assert by_role["reviewer"].state == "pending", (
            "partial liveness (1/2 sessions) must NOT be reported as alive; "
            "B4 would skip launching the missing instance"
        )

    def test_version_mismatch_raises(self, tmp_path):
        bad = tmp_path / "v1.toml"
        bad.write_text('version = 1\nproject_name = "install"\n')
        with pytest.raises(ValueError) as exc_info:
            ancestor_brief.load_context_from_profile(project="install", profile_path=bad)
        assert "v2" in str(exc_info.value)

    def test_project_mismatch_raises(self, v2_profile):
        with pytest.raises(ValueError) as exc_info:
            ancestor_brief.load_context_from_profile(project="cartooner", profile_path=v2_profile)
        assert "install" in str(exc_info.value) and "cartooner" in str(exc_info.value)

    def test_missing_tenant_raises(self, tmp_path):
        incomplete = tmp_path / "no-tenant.toml"
        incomplete.write_text('version = 2\nproject_name = "x"\nseats = ["ancestor", "planner"]\n')
        with pytest.raises(ValueError) as exc_info:
            ancestor_brief.load_context_from_profile(project="x", profile_path=incomplete)
        assert "openclaw_frontstage_agent" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────
# Section B — YAML front-matter shape
# ─────────────────────────────────────────────────────────────────────

def _extract_yaml(rendered: str) -> tuple[dict, str]:
    """Split the brief into its YAML front matter + markdown body."""
    if not rendered.startswith("---"):
        raise AssertionError("brief must open with `---`")
    parts = rendered.split("---", 2)
    if len(parts) < 3:
        raise AssertionError("brief must have a second `---` closing the front matter")
    import yaml  # optional; if missing, parse manually via tomllib-ish scaffolding
    return yaml.safe_load(parts[1]), parts[2]


class TestRenderEnvelope:

    def test_envelope_opens_with_yaml_delimiter(self, v2_profile, no_tmux):
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        out = ancestor_brief.render_brief(ctx)
        assert out.startswith("---\n"), "brief must start with ---"
        # Must contain a closing ---
        assert out.count("---") >= 2

    def test_yaml_parses_cleanly(self, v2_profile, no_tmux):
        pytest.importorskip("yaml")
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        meta, _ = _extract_yaml(ancestor_brief.render_brief(ctx))
        assert meta["brief_schema"] == "memory-bootstrap"
        assert meta["brief_schema_version"] == "0.1"
        assert meta["project"] == "install"
        assert meta["profile_version"] == 2
        assert meta["openclaw_tenant"] == "yu"
        assert len(meta["seats_declared"]) == 6

    def test_yaml_contains_phase_a_checklist_in_order(self, v2_profile, no_tmux):
        pytest.importorskip("yaml")
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        meta, _ = _extract_yaml(ancestor_brief.render_brief(ctx))
        assert meta["checklist_phase_a"] == list(ancestor_brief.DEFAULT_PHASE_A_CHECKLIST)

    def test_yaml_feishu_sender_is_memory(self, v2_profile, no_tmux):
        pytest.importorskip("yaml")
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        meta, _ = _extract_yaml(ancestor_brief.render_brief(ctx))
        assert meta["observability"]["feishu_sender_seat"] == "memory"
        assert meta["observability"]["feishu_lark_cli_identity"] == "planner"

    def test_yaml_custom_whitelist_respected(self, v2_profile, no_tmux):
        pytest.importorskip("yaml")
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        meta, _ = _extract_yaml(ancestor_brief.render_brief(ctx))
        # The profile declares 5 events (includes config-drift-recovery)
        assert "config-drift-recovery" in meta["observability"]["feishu_events_whitelist"]


# ─────────────────────────────────────────────────────────────────────
# Section C — body contents
# ─────────────────────────────────────────────────────────────────────

class TestBody:

    def test_body_names_ancestor_rules(self, v2_profile, no_tmux):
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        out = ancestor_brief.render_brief(ctx)
        # Responsibility hooks — the body must remind ancestor of its
        # three hard rules so a skill drift can't break them silently.
        assert "NEVER upgrade" in out or "NEVER upgrade" in out.replace("\n", " ")
        assert "NEVER retire" in out or "NEVER retire" in out.replace("\n", " ")
        assert "sender_seat: memory" in out

    def test_body_references_phase_a_and_phase_b(self, v2_profile, no_tmux):
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        out = ancestor_brief.render_brief(ctx)
        assert "Phase-A" in out
        assert "Phase-B" in out

    def test_body_references_bootstrap_spec(self, v2_profile, no_tmux):
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        out = ancestor_brief.render_brief(ctx)
        assert "docs/schemas/memory-bootstrap-brief.md" in out


# ─────────────────────────────────────────────────────────────────────
# Section D — write + idempotency
# ─────────────────────────────────────────────────────────────────────

class TestWrite:

    def test_write_creates_directories(self, v2_profile, tmp_path, no_tmux, monkeypatch):
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        out = tmp_path / "handoffs" / "deep" / "memory-bootstrap.md"
        written = ancestor_brief.write_brief(ctx, out_path=out)
        assert written == out and out.is_file()

    def test_write_is_idempotent_same_context(self, v2_profile, tmp_path, no_tmux):
        ctx = ancestor_brief.load_context_from_profile(
            project="install", profile_path=v2_profile,
        )
        out = tmp_path / "brief.md"
        first = ancestor_brief.write_brief(ctx, out_path=out)
        content_1 = first.read_text()
        # Re-render and compare AFTER stripping the generated_at timestamp
        # (which changes per call by design — the brief must be fresh on
        # each install run but structurally identical for the same context).
        second = ancestor_brief.write_brief(ctx, out_path=out)
        content_2 = second.read_text()
        # Drop the `brief_generated_at` line for diff purposes
        stripped_1 = "\n".join(l for l in content_1.splitlines() if not l.startswith("brief_generated_at:"))
        stripped_2 = "\n".join(l for l in content_2.splitlines() if not l.startswith("brief_generated_at:"))
        assert stripped_1 == stripped_2, "brief must be deterministic aside from timestamp"


# ─────────────────────────────────────────────────────────────────────
# Section E — CLI entrypoint
# ─────────────────────────────────────────────────────────────────────

class TestCLI:

    def test_missing_profile_returns_2(self, tmp_path, capsys):
        missing = tmp_path / "nope.toml"
        rc = ancestor_brief.main(["--project", "demo", "--profile", str(missing)])
        assert rc == 2
        err = capsys.readouterr().err
        assert "profile not found" in err

    def test_dry_run_prints_brief_to_stdout(self, v2_profile, capsys, monkeypatch):
        monkeypatch.setattr(ancestor_brief, "_tmux_session_alive", lambda _: False)
        rc = ancestor_brief.main([
            "--project", "install", "--profile", str(v2_profile), "--dry-run",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert out.startswith("---")
        assert "memory-bootstrap" in out

    def test_json_context_is_parseable(self, v2_profile, capsys, monkeypatch):
        monkeypatch.setattr(ancestor_brief, "_tmux_session_alive", lambda _: False)
        rc = ancestor_brief.main([
            "--project", "install", "--profile", str(v2_profile), "--json-context",
        ])
        assert rc == 0
        import json
        parsed = json.loads(capsys.readouterr().out)
        assert parsed["project"] == "install"
        assert parsed["profile_version"] == 2


# ─────────────────────────────────────────────────────────────────────
# Section F — constants & schema stability
# ─────────────────────────────────────────────────────────────────────

class TestSchemaConstants:

    def test_schema_version_is_0_1(self):
        assert ancestor_brief.BRIEF_SCHEMA_VERSION == "0.1"

    def test_phase_a_checklist_has_seven_steps(self):
        """v0.1.1 architect edit removed B8-await-operator-ack; now 7 steps."""
        assert len(ancestor_brief.DEFAULT_PHASE_A_CHECKLIST) == 7

    def test_checklist_tokens_are_stable_identifiers(self):
        for token in ancestor_brief.DEFAULT_PHASE_A_CHECKLIST:
            assert token.startswith("B"), f"{token!r}: expected B-prefixed step id"

    def test_checklist_no_operator_ack_gate(self):
        """B8 explicitly removed — Phase A → Phase B is automatic."""
        assert not any("await-operator-ack" in t for t in ancestor_brief.DEFAULT_PHASE_A_CHECKLIST)
        # And B2/B5 have the new semantics
        tokens = set(ancestor_brief.DEFAULT_PHASE_A_CHECKLIST)
        assert "B2-verify-or-launch-memory" in tokens
        assert "B5-verify-feishu-group-binding" in tokens
