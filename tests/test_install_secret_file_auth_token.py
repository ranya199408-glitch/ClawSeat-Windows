from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SECRETS_SH = REPO / "scripts" / "install" / "lib" / "secrets.sh"


def _run_secret_token_reader(secret_file: Path) -> subprocess.CompletedProcess[str]:
    command = (
        f"source {shlex.quote(str(SECRETS_SH))}; "
        f"_secret_file_auth_token {shlex.quote(str(secret_file))}"
    )
    return subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\n", "fixture-anthropic-auth"),
        ("export ANTHROPIC_API_KEY=<ANTHROPIC_API_KEY>\n", "fixture-anthropic-api"),
        ("export CLAUDE_CODE_OAUTH_TOKEN=<CLAUDE_CODE_OAUTH_TOKEN>\n", "fixture-claude-oauth"),
    ],
)
def test_secret_file_auth_token_parses_supported_keys(
    tmp_path: Path,
    content: str,
    expected: str,
) -> None:
    secret_file = tmp_path / "secret.env"
    secret_file.write_text(content, encoding="utf-8")

    result = _run_secret_token_reader(secret_file)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected

