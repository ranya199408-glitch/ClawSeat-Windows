from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
I18N = REPO / "scripts" / "install" / "lib" / "i18n.sh"


def test_i18n_lang_switch_round_trips_between_zh_and_en() -> None:
    """i18n_set changes subsequent i18n_get output mid-session."""
    script = f"""
source {shlex.quote(str(I18N))}
i18n_set zh
i18n_get kind_first_prompt
i18n_set en
i18n_get kind_first_prompt
i18n_set /zh
i18n_get kind_first_prompt
"""
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "INSTALL_LIB_DIR": str(I18N.parent)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines == [
        "选择项目类型 / Choose project mode:",
        "Choose project mode:",
        "选择项目类型 / Choose project mode:",
    ]
