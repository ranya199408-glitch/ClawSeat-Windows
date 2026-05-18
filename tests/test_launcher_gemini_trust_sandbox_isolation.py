from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_HELPERS_PATH = Path(__file__).with_name("test_launcher_gemini_trust_seed.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_launcher_gemini_trust_seed_helpers", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_run_bash = _HELPERS._run_bash


def test_prepare_gemini_home_keeps_trusted_folders_isolated_from_seed_source(tmp_path: Path) -> None:
    real_home = tmp_path / "real_home"
    runtime_home = tmp_path / "runtime_home"
    real_home.mkdir(parents=True)
    runtime_home.mkdir(parents=True)

    source_gemini = real_home / ".gemini"
    source_gemini.mkdir(parents=True, exist_ok=True)
    (source_gemini / "auth.json").write_text('{"token":"real"}', encoding="utf-8")
    (source_gemini / "trustedFolders.json").write_text(
        json.dumps({"/tmp/fake-home": "TRUST_FOLDER"}, indent=2),
        encoding="utf-8",
    )

    result = _run_bash(
        real_home,
        "\n".join(
            [
                f"seed_user_tool_dirs {runtime_home!s}",
                f"prepare_gemini_home {runtime_home!s} /tmp/sandbox-workdir",
            ]
        ),
    )

    assert result.returncode == 0, result.stderr
    sandbox_gemini = runtime_home / ".gemini"
    assert sandbox_gemini.is_dir()
    assert not sandbox_gemini.is_symlink()
    assert (sandbox_gemini / "auth.json").is_symlink()
    assert (sandbox_gemini / "auth.json").readlink() == source_gemini / "auth.json"

    sandbox_trust = json.loads((sandbox_gemini / "trustedFolders.json").read_text(encoding="utf-8"))
    assert sandbox_trust["/tmp/fake-home"] == "TRUST_FOLDER"
    assert sandbox_trust["/tmp/sandbox-workdir"] == "TRUST_FOLDER"
    assert json.loads((source_gemini / "trustedFolders.json").read_text(encoding="utf-8")) == {
        "/tmp/fake-home": "TRUST_FOLDER",
    }
