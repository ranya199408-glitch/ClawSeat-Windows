from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "core" / "lib"))

import env_utils  # noqa: E402


@pytest.mark.parametrize(
    "text, expected",
    [
        ("export KEY=val", {"KEY": "val"}),
        ('KEY="val with spaces"', {"KEY": "val with spaces"}),
        ("EMPTY=\n", {"EMPTY": ""}),
        ('UNICODE="café ∆"', {"UNICODE": "café ∆"}),
    ],
)
def test_parse_env_text_handles_common_shell_forms(text: str, expected: dict[str, str]) -> None:
    assert env_utils.parse_env_text(text) == expected


def test_parse_env_text_ignores_comments_and_malformed_lines() -> None:
    text = """\
    # comment
    not-a-pair
    =missing_key
    KEY=value
    """
    assert env_utils.parse_env_text(text) == {"KEY": "value"}


def test_parse_env_file_reads_from_path_and_missing_file_returns_empty(tmp_path: Path) -> None:
    env_file = tmp_path / "sample.env"
    env_file.write_text(
        "export API_KEY=<API_KEY>\nSPACED=\"value with spaces\"\nEMPTY=\n",
        encoding="utf-8",
    )

    assert env_utils.parse_env_file(env_file) == {
        "API_KEY": "<API_KEY>",
        "SPACED": "value with spaces",
        "EMPTY": "",
    }
    assert env_utils.parse_env_file(tmp_path / "missing.env") == {}
