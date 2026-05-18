"""Tests for do_koder_bind --feishu-group-id (Sub-1 of FIX-KODER-BIND-AND-DOCS-BUNDLE)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_LIB = _REPO / "core" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from agent_admin_layered import KoderBindError, do_koder_bind  # noqa: E402


def _make_machine_cfg(workspace: Path):
    workspace.mkdir(parents=True, exist_ok=True)
    # do_koder_bind validates that WORKSPACE_CONTRACT.toml exists.
    (workspace / "WORKSPACE_CONTRACT.toml").write_text(
        'seat_id = "koder"\nproject = ""\n', encoding="utf-8"
    )
    tenant = SimpleNamespace(
        name="koder",
        workspace=workspace,
        openclaw_json_path=workspace / "openclaw.json",
    )
    return SimpleNamespace(
        tenants={"koder": tenant},
        openclaw_tenants={"koder": tenant},
        real_home=workspace.parent,
    )


def test_koder_bind_with_group_id_writes_real_value(tmp_path: Path) -> None:
    """--feishu-group-id <FEISHU_GROUP_ID> must be written to the binding file."""
    from project_binding import load_binding
    ws = tmp_path / "workspace-koder"
    result = do_koder_bind(
        "testproject", "koder",
        group_id="<FEISHU_GROUP_ID>",
        machine_cfg=_make_machine_cfg(ws),
        binding_home=tmp_path,
    )
    binding = load_binding("testproject", home=tmp_path)
    assert binding is not None
    assert binding.feishu_group_id == "<FEISHU_GROUP_ID>"


def test_koder_bind_without_group_id_keeps_placeholder_backward_compat(tmp_path: Path) -> None:
    """Omitting --feishu-group-id must write '<FEISHU_GROUP_ID>' placeholder."""
    from project_binding import load_binding
    ws = tmp_path / "workspace-koder"
    result = do_koder_bind(
        "testproject2", "koder",
        machine_cfg=_make_machine_cfg(ws),
        binding_home=tmp_path,
    )
    binding = load_binding("testproject2", home=tmp_path)
    assert binding is not None
    assert binding.feishu_group_id == "<FEISHU_GROUP_ID>"


def test_koder_bind_invalid_group_id_format_raises(tmp_path: Path) -> None:
    """group_id that doesn't match oc_<16+ chars> must raise KoderBindError."""
    with pytest.raises(KoderBindError, match="invalid feishu_group_id"):
        do_koder_bind(
            "testproject3", "koder",
            group_id="oc_short",
            machine_cfg=_make_machine_cfg(tmp_path / "ws"),
        )


def test_koder_bind_invalid_group_id_no_oc_prefix_raises(tmp_path: Path) -> None:
    """group_id without oc_ prefix must raise KoderBindError."""
    with pytest.raises(KoderBindError, match="invalid feishu_group_id"):
        do_koder_bind(
            "testproject4", "koder",
            group_id="bad_not_oc_prefix_1234567890",
            machine_cfg=_make_machine_cfg(tmp_path / "ws"),
        )
