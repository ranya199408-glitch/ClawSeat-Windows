from pathlib import Path


def test_memory_reference_documents_openclaw_skill_install_protocol() -> None:
    path = Path("core/skills/memory-oracle/references/openclaw-skill-install-protocol.md")
    text = path.read_text(encoding="utf-8")
    assert "OpenClaw Skill Install Protocol" in text
    assert "~/.openclaw" in text
    assert "clawseat-intake" in text
    assert "clawseat-koder" in text
    assert "install_skill_tier_for_home openclaw" in text
    assert "Per-Agent Activation" in text
    assert "Manual Backfill" in text
    assert "Reverse Sync" in text
    assert "SSOT" in text
