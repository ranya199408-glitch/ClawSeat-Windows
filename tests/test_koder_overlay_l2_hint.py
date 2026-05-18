from __future__ import annotations

import importlib.util
from pathlib import Path


_HELPERS_PATH = Path(__file__).with_name("test_apply_koder_overlay.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_apply_koder_overlay_helpers_l2", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_run = _HELPERS._run
_seed_home = _HELPERS._seed_home


def test_dry_run_prints_layer2_manual_configuration_hint(tmp_path: Path) -> None:
    real_home = _seed_home(tmp_path)
    binding_dir = real_home / ".agents" / "tasks" / "install"
    binding_dir.mkdir(parents=True, exist_ok=True)
    (binding_dir / "PROJECT_BINDING.toml").write_text(
        "\n".join(
            [
                'project = "install"',
                'feishu_sender_app_id = "<FEISHU_APP_ID>"',
                'feishu_sender_mode = "auto"',
                'openclaw_koder_agent = "a"',
            ]
        ),
        encoding="utf-8",
    )

    result = _run(["--dry-run", "install", "<FEISHU_GROUP_ID>"], real_home=real_home)

    assert result.returncode == 0, result.stderr
    assert "koder overlay applied" in result.stdout
    assert "https://open.feishu.cn/app" in result.stdout
    assert "<FEISHU_APP_ID>" in result.stdout
    assert "接收群聊所有消息" in result.stdout
