"""F10 regression: configure_koder_feishu.py correctly flips requireMention."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "core" / "skills" / "clawseat-install" / "scripts" / "configure_koder_feishu.py"


@pytest.fixture
def fake_openclaw(tmp_path):
    home = tmp_path / ".openclaw"
    home.mkdir()
    config = {
        "channels": {
            "feishu": {
                "accounts": {
                    "yu": {"appId": "X", "groups": {}},
                    "main": {
                        "appId": "Y",
                        "groups": {"<FEISHU_GROUP_ID>": {"requireMention": False}},
                        "requireMention": True,
                    },
                }
            }
        }
    }
    (home / "openclaw.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return home


def _run(args: list[str], openclaw_home: Path) -> int:
    import subprocess
    env = {"HOME": str(openclaw_home.parent)}
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--openclaw-home", str(openclaw_home), *args],
        capture_output=True, text=True, env={**__import__("os").environ, **env},
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
    return result.returncode


def test_set_account_level_no_mention(fake_openclaw):
    rc = _run(["--agent", "yu"], fake_openclaw)
    assert rc == 0
    config = json.loads((fake_openclaw / "openclaw.json").read_text())
    assert config["channels"]["feishu"]["accounts"]["yu"]["requireMention"] is False


def test_set_group_level_no_mention(fake_openclaw):
    rc = _run(["--agent", "yu", "--group-id", "<FEISHU_GROUP_ID>"], fake_openclaw)
    assert rc == 0
    config = json.loads((fake_openclaw / "openclaw.json").read_text())
    assert (
        config["channels"]["feishu"]["accounts"]["yu"]["groups"]["<FEISHU_GROUP_ID>"]["requireMention"]
        is False
    )


def test_unknown_agent_errors(fake_openclaw):
    rc = _run(["--agent", "nonexistent"], fake_openclaw)
    assert rc != 0
