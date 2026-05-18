from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import agent_admin_workspace as aaw  # noqa: E402


def test_workspace_render_includes_canonical_dispatch_receipt_and_fanout_surface() -> None:
    engineer = SimpleNamespace(
        role="memory",
        _project_record=None,
        _project_engineers={},
        _engineer_order=[],
    )

    text = "\n".join(aaw.render_communication_protocol_lines(engineer, "install"))

    assert "canonical dispatch" in text
    assert "dispatch_task.py" in text
    assert "complete_handoff.py" in text
    assert "Fan-out Default" in text
    assert "2+" in text
    assert "fan-out" in text
    assert "fan out independent sub-goals via the seat dispatch primitive" in text
    assert "or `complete_handoff.py`" not in text
