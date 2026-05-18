from __future__ import annotations

import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
INSTALL = REPO / "scripts" / "install.sh"


def test_install_help_lists_all_provider_modes() -> None:
    result = subprocess.run(
        ["bash", str(INSTALL), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    output = result.stdout
    for provider in (
        "oauth",
        "anthropic_console",
        "minimax",
        "deepseek",
        "ark",
        "xcode-best",
        "custom_api",
    ):
        assert provider in output
    assert "Provider modes" in output
    assert "option 3" in output
    assert "option 8" in output
    assert "Non-TTY" in output
    assert "--provider <mode>" in output
