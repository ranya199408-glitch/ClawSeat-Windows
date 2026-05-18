from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from agent_admin_crud_engineer import EngineerCrud  # noqa: E402


def test_workspace_regenerate_preserves_operator_custom_block(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    custom_block = "\n".join(
        [
            "<!-- OPERATOR-CUSTOM-START -->",
            "operator-local prompt survives template refresh",
            "<!-- OPERATOR-CUSTOM-END -->",
        ]
    )
    existing = "\n".join(
        [
            "# AGENTS.md",
            "stale rendered content",
            custom_block,
            "old footer",
            "",
        ]
    )
    rendered = "\n".join(
        [
            "# AGENTS.md",
            "latest SKILL content",
            "canonical dispatch",
            "Fan-out Default",
            "",
        ]
    )
    target = workspace / "AGENTS.md"
    target.write_text(existing, encoding="utf-8")

    def apply_template(_session, _project) -> None:
        target.write_text(rendered, encoding="utf-8")

    hooks = SimpleNamespace(
        error_cls=RuntimeError,
        render_template_text=lambda _tool, _session, _project: {"AGENTS.md": rendered},
        ensure_dir=lambda path: path.mkdir(parents=True, exist_ok=True),
        apply_template=apply_template,
    )
    session = SimpleNamespace(
        engineer_id="builder",
        session="install-builder",
        tool="claude",
        workspace=str(workspace),
    )
    project = SimpleNamespace(name="install")

    EngineerCrud(hooks)._regenerate_one_workspace(session, project, assume_yes=True)

    updated = target.read_text(encoding="utf-8")
    assert custom_block in updated
    assert "latest SKILL content" in updated
    assert "stale rendered content" not in updated
    assert list(workspace.glob("AGENTS.md.bak.*"))
