import os
from pathlib import Path


def test_solo_b_smoke_script_is_executable() -> None:
    """Smoke script exists and contains manual header."""
    script = Path("tests/test_solo_b_e2e_smoke.sh")
    assert script.exists()
    content = script.read_text(encoding="utf-8")
    assert "manual" in content
    assert "clawseat-solo" in content
    assert os.access(script, os.X_OK)
