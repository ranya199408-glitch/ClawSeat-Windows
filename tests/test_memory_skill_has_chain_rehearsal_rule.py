from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
MEMORY_ORACLE = REPO / "core" / "skills" / "memory-oracle" / "SKILL.md"
CLAWSEAT_MEMORY = REPO / "core" / "skills" / "clawseat-memory" / "SKILL.md"
TEMPLATE = (
    REPO
    / "core"
    / "skills"
    / "memory-oracle"
    / "references"
    / "post-spawn-chain-rehearsal-template.md"
)


def test_memory_oracle_documents_post_spawn_chain_rehearsal_rule() -> None:
    text = MEMORY_ORACLE.read_text(encoding="utf-8")

    assert "Post-Spawn Chain Rehearsal" in text
    assert "MUST" in text or "必须" in text
    assert "references/post-spawn-chain-rehearsal-template.md" in text
    assert "Phase-A kickoff" in text
    assert "complete_handoff.py" in text
    assert "send-and-verify.sh" in text
    assert "do NOT proceed to real task dispatch" in text


def test_clawseat_memory_documents_post_spawn_chain_rehearsal_rule() -> None:
    text = CLAWSEAT_MEMORY.read_text(encoding="utf-8")

    assert "Post-Spawn Chain Rehearsal" in text
    assert "MUST" in text or "必须" in text
    assert "references/post-spawn-chain-rehearsal-template.md" in text
    assert "complete_handoff.py" in text
    assert "planner/DELIVERY.md" in text


def test_post_spawn_chain_rehearsal_template_exists_and_is_complete() -> None:
    assert TEMPLATE.is_file()
    text = TEMPLATE.read_text(encoding="utf-8")

    assert "chain-rehearsal" in text
    assert "self-report" in text or "self-introduce" in text
    assert "complete_handoff.py" in text
    assert "send-and-verify.sh" in text
    assert "notify_on_done" in text
    assert "verdict=PASS" in text
