from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_trust_folder_auto_enter(tmp_path: Path) -> None:
    """Post-spawn helper sends Enter when pane shows a Trust folder prompt."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "tmux.log"
    fake_tmux = bin_dir / "tmux"
    fake_tmux.write_text(
        """#!/usr/bin/env bash
if [[ "$*" == *"capture-pane"* ]]; then
  printf 'Quick safety check:\\nTrust folder\\n'
  exit 0
fi
if [[ "$*" == *"send-keys"* ]]; then
  printf '%s\\n' "$*" >> "$TMUX_LOG"
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_tmux.chmod(0o755)

    script = f"""
source {REPO / 'scripts/install/lib/window.sh'}
note() {{ :; }}
post_spawn_trust_folder_auto_enter install-memory-claude claude
"""
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "TMUX_LOG": str(log),
        "CLAWSEAT_TRUST_PROMPT_SLEEP_SECONDS": "0",
    }
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    sent = log.read_text(encoding="utf-8")
    assert 'send-keys -t =install-memory-claude  Enter' in sent
