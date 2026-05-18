from __future__ import annotations

import re
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO / "core" / "skills" / "clawseat-install" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import init_koder  # noqa: E402


TEMPLATE_DIR = REPO / "core" / "templates" / "koder-workspace-tools"
EXPECTED_TEMPLATES = {
    "index.md.tmpl",
    "dispatch.md.tmpl",
    "project.md.tmpl",
    "seat.md.tmpl",
    "memory.md.tmpl",
    "install.md.tmpl",
}


def test_init_koder_tool_templates_exist_and_use_simple_placeholders() -> None:
    assert {path.name for path in TEMPLATE_DIR.glob("*.md.tmpl")} == EXPECTED_TEMPLATES

    placeholder_re = re.compile(r"{{[A-Za-z0-9_]+}}")
    for name in EXPECTED_TEMPLATES:
        text = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
        assert text.startswith("# TOOLS")
        assert "{%" not in text
        assert "{{#if" not in text
        assert "{{#for" not in text
        assert all(match.group(0).startswith("{{") for match in placeholder_re.finditer(text))


def test_render_tools_outputs_have_no_unresolved_template_placeholders(tmp_path: Path) -> None:
    renderers = [
        init_koder.render_tools_index(REPO, heartbeat_owner="koder", notify_target="planner"),
        init_koder.render_tools_dispatch(REPO),
        init_koder.render_tools_project(REPO, heartbeat_owner="koder", workspace_path=tmp_path / "workspace-koder"),
        init_koder.render_tools_seat(REPO, heartbeat_owner="koder", backend_seats=["planner", "builder-1"]),
        init_koder.render_tools_memory(REPO, heartbeat_owner="koder"),
        init_koder.render_tools_install(REPO),
    ]

    for rendered in renderers:
        assert "{{" not in rendered
        assert "}}" not in rendered


def test_render_tools_seat_keeps_backend_branching_in_python() -> None:
    with_backends = init_koder.render_tools_seat(REPO, heartbeat_owner="koder", backend_seats=["planner", "builder-1"])
    without_backends = init_koder.render_tools_seat(REPO, heartbeat_owner="koder", backend_seats=[])

    assert "`planner`, `builder-1`" in with_backends
    assert "--seat <planner|builder-1>" in with_backends
    assert "## 可拉起的 backend seat\n\n(none)" in without_backends
    assert "--seat <seat-id>" in without_backends
