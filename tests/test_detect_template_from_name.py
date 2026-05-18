from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
DETECT = REPO / "scripts" / "install" / "lib" / "detect.sh"


def _template_for(name: str) -> str:
    env = {
        **os.environ,
        "HOME": os.environ.get("HOME", ""),
        "CLAWSEAT_ROOT": str(REPO),
    }
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"source {shlex.quote(str(DETECT))}; detect_template_from_name {shlex.quote(name)}",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("personal-solo-lab", "clawseat-solo"),
        ("MinimalDraft", "clawseat-solo"),
        ("web-api-tool", "clawseat-engineering"),
        ("GAME-backend", "clawseat-engineering"),
        ("story-studio", "clawseat-creative"),
        ("", "clawseat-creative"),
    ],
)
def test_detect_template_from_name_maps_project_intent(name: str, expected: str) -> None:
    """Project names infer solo, engineering, or creative defaults."""
    assert _template_for(name) == expected
