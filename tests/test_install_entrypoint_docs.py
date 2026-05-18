from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def _read(relpath: str) -> str:
    return (_REPO / relpath).read_text(encoding="utf-8")


def test_entrypoint_skills_point_to_install_sh_not_v05_launch_path() -> None:
    clawseat = _read("core/skills/clawseat/SKILL.md")
    install = _read("core/skills/clawseat-install/SKILL.md")
    resume = _read("core/skills/cs/SKILL.md")

    assert "route to the v0.5 install playbook" not in clawseat
    assert "koder remains the tenant frontstage" not in clawseat

    assert "bash scripts/install.sh" in install
    assert "Somewhere inside `docs/INSTALL.md` is a launch step that calls" not in install
    assert "[`scripts/launch_ancestor.sh`](../../../scripts/launch_ancestor.sh) — one-call ancestor launch" not in install
    assert "runtime-selection.json" not in install
    assert "parallelizes seat startup" not in install

    assert "valid v0.5" not in resume
    assert "scripts/launch_ancestor.sh" not in resume


def test_canonical_docs_mark_legacy_brief_reference_and_install_entry() -> None:
    readme = _read("README.md")
    iterm = _read("docs/ITERM_TMUX_REFERENCE.md")
    brief_schema = _read("docs/schemas/memory-bootstrap-brief.md")
    launcher_readme = _read("core/launchers/README.md")
    plugin_readme = _read("shells/openclaw-plugin/README.md")

    assert "docs/INSTALL.md" in readme          # main install doc referenced
    assert "scripts/install.sh" in readme        # install script referenced
    assert "launch_ancestor.sh" not in readme    # old v0.5 launch path absent

    assert "v0.7 主链路默认走 `docs/INSTALL.md` 与 `scripts/install.sh`" in iterm
    assert "v0.5 主链路默认走 `docs/INSTALL.md` 与 `scripts/launch_ancestor.sh`" not in iterm

    assert "Legacy reference" in brief_schema
    assert "core/templates/memory-bootstrap.template.md" in brief_schema
    assert "When this file conflicts with" in brief_schema

    assert "the v0.7 install playbook" in launcher_readme
    assert "the v0.5 install playbook that drives ancestor launch" not in launcher_readme

    assert "v0.7 `scripts/install.sh`" in plugin_readme
    assert "follow the v0.5 playbook" not in plugin_readme

    assert not (_REPO / "scripts" / "launch_ancestor.sh").exists()
