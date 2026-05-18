"""Tests for install.sh --template flag + kind-first prompt skip conditions.

Verifies:
1. --template clawseat-creative is accepted; CLAWSEAT_TEMPLATE_NAME propagated
2. --template bad dies with exit 2
3. Omitting --template uses clawseat-engineering
4. BOOTSTRAP_TEMPLATE_PATH follows --template (patch for fd7cd74 bug)
5. prompt_kind_first_flow: skipped (no hang) when --project or --template explicit
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_INSTALL = _REPO / "scripts" / "install.sh"


def _run(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PYTHON_BIN": sys.executable,
        "CLAWSEAT_REAL_HOME": str(tmp_path / "home"),
    }
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        ["bash", str(_INSTALL)] + args,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_template_creative_accepted(tmp_path: Path) -> None:
    """--template clawseat-creative exits 0 in dry-run."""
    result = _run(["--project", "testproj", "--template", "clawseat-creative", "--dry-run"], tmp_path)
    assert result.returncode == 0, result.stderr
    # The template name must appear in the dry-run output (written to project-local.toml)
    assert "clawseat-creative" in result.stdout, f"expected template name in output:\n{result.stdout}"


def test_template_engineering_accepted(tmp_path: Path) -> None:
    """--template clawseat-engineering exits 0 in dry-run."""
    result = _run(["--project", "testproj", "--template", "clawseat-engineering", "--dry-run"], tmp_path)
    assert result.returncode == 0, result.stderr


def test_template_invalid_dies_exit_2(tmp_path: Path) -> None:
    """--template bad_value exits 2 with INVALID_TEMPLATE error code."""
    result = _run(["--project", "testproj", "--template", "bad_value", "--dry-run"], tmp_path)
    assert result.returncode == 2, f"expected exit 2, got {result.returncode}: {result.stderr}"
    assert "INVALID_TEMPLATE" in result.stderr or "template" in result.stderr.lower()


def test_template_default_when_omitted(tmp_path: Path) -> None:
    """Omitting --template uses clawseat-engineering."""
    result = _run(["--project", "testproj", "--dry-run"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert "clawseat-engineering" in result.stdout, f"expected default template in output:\n{result.stdout}"


def test_memory_tool_defaults_to_template_claude(tmp_path: Path) -> None:
    """clawseat-creative launches the memory primary seat with template Claude OAuth by default."""
    result = _run(["--project", "memclaudedefault", "--template", "clawseat-creative", "--provider", "oauth", "--dry-run"], tmp_path)
    output = result.stdout + result.stderr
    assert result.returncode == 0, result.stderr
    assert "agent-launcher.sh --headless --tool claude --auth oauth" in output


def test_memory_tool_claude_override(tmp_path: Path) -> None:
    """--memory-tool claude keeps the memory primary seat on the Claude launcher path."""
    result = _run(
        ["--project", "memclaude", "--template", "clawseat-creative", "--memory-tool", "claude", "--provider", "oauth", "--dry-run"],
        tmp_path,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, result.stderr
    assert "agent-launcher.sh --headless --tool claude" in output
    assert "--auth chatgpt" not in output


def test_memory_tool_gemini_override(tmp_path: Path) -> None:
    """--memory-tool gemini launches the memory primary seat with Gemini OAuth."""
    result = _run(
        ["--project", "memgemini", "--template", "clawseat-creative", "--memory-tool", "gemini", "--dry-run"],
        tmp_path,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, result.stderr
    assert "memory-tool=gemini auth=oauth; skip Claude provider selection" in output
    assert "agent-launcher.sh --headless --tool gemini --auth oauth" in output
    assert "LAUNCHER_CUSTOM_MODEL" not in output


def test_bootstrap_template_path_follows_template_flag(tmp_path: Path) -> None:
    """BOOTSTRAP_TEMPLATE_PATH must use the --template value, not the hardcoded default.

    Regression for fd7cd74: BOOTSTRAP_TEMPLATE_DIR was computed at global init
    time before parse_args ran, so --template was ignored in the path.
    """
    result = _run(["--project", "pathtest", "--template", "clawseat-creative", "--dry-run"], tmp_path)
    assert result.returncode == 0, result.stderr

    # Filter to lines that reference the template file path or bootstrap command.
    template_lines = [
        line for line in result.stdout.splitlines()
        if "template.toml" in line or ("bootstrap --template" in line)
    ]
    assert template_lines, f"No template-path lines found in dry-run output:\n{result.stdout}"

    # Every such line must reference clawseat-creative.
    for line in template_lines:
        assert "clawseat-creative" in line, (
            f"Template line references wrong template (expected clawseat-creative):\n  {line}"
        )


# ── prompt_kind_first_flow skip-condition tests (d0bfc52) ──────────────────


def _run_no_tty(args: list[str], tmp_path: Path, timeout: int = 8) -> subprocess.CompletedProcess[str]:
    """Run install.sh with stdin from /dev/null (non-TTY) and a timeout."""
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PYTHON_BIN": sys.executable,
        "CLAWSEAT_REAL_HOME": str(tmp_path / "home"),
    }
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    with open(os.devnull, "rb") as devnull:
        return subprocess.run(
            ["bash", str(_INSTALL)] + args,
            stdin=devnull,
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=timeout,
        )


def test_kind_first_prompt_skipped_when_project_explicit(tmp_path: Path) -> None:
    """--project flag sets _PROJECT_EXPLICIT=1 → prompt_kind_first_flow returns immediately.
    Non-TTY + explicit --project must not hang and must exit 0 in dry-run."""
    result = _run_no_tty(["--project", "ci-proj", "--dry-run"], tmp_path)
    assert result.returncode == 0, f"must not hang or fail; stderr:\n{result.stderr}"
    assert "dry-run" in result.stdout or "Step" in result.stdout


def test_kind_first_prompt_skipped_when_template_explicit(tmp_path: Path) -> None:
    """--template flag sets _TEMPLATE_EXPLICIT=1 → prompt_kind_first_flow returns immediately."""
    result = _run_no_tty(["--template", "clawseat-creative", "--project", "ci-proj", "--dry-run"], tmp_path)
    assert result.returncode == 0, f"must not hang; stderr:\n{result.stderr}"


def test_kind_first_prompt_skipped_non_tty_both_flags(tmp_path: Path) -> None:
    """Non-TTY with both flags: no interactive prompt, full dry-run proceeds."""
    result = _run_no_tty(
        ["--project", "ci-eng", "--template", "clawseat-engineering", "--dry-run"], tmp_path
    )
    assert result.returncode == 0, result.stderr
    assert "clawseat-engineering" in result.stderr  # dry-run echoes template name
