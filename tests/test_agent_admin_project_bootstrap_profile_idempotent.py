from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_agent_admin_project_bootstrap_renders_profile import _run_bootstrap, _write_local_toml


def test_project_bootstrap_does_not_overwrite_existing_dynamic_profile(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = "ll-idempotent"
    profile = home / ".agents" / "profiles" / f"{project}-profile-dynamic.toml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        "\n".join(
            [
                f'profile_name = "{project}"',
                'heartbeat_owner = "operator-custom"',
                'seats = ["operator"]',
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_bootstrap(home, _write_local_toml(tmp_path, project))

    assert result.returncode == 0, result.stderr
    text = profile.read_text(encoding="utf-8")
    assert 'heartbeat_owner = "operator-custom"' in text
    assert 'seats = ["operator"]' in text
    assert 'seats = ["memory", "builder", "planner"]' not in text
