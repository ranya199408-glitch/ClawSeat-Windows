from __future__ import annotations
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from seat_skill_mapping import SEAT_SKILL_MAP, role_skill_for_seat

def test_seat_skill_map_canonical_roles() -> None:
    assert SEAT_SKILL_MAP['builder'] == 'builder'
    assert SEAT_SKILL_MAP['reviewer'] == 'reviewer'
    assert SEAT_SKILL_MAP['patrol'] == 'patrol'
    assert 'qa' not in SEAT_SKILL_MAP
    assert SEAT_SKILL_MAP['designer'] == 'designer'
    assert SEAT_SKILL_MAP['ancestor'] == 'clawseat-ancestor'
    assert SEAT_SKILL_MAP['planner'] == 'planner'
    assert SEAT_SKILL_MAP['memory'] == 'memory-oracle'

def test_role_skill_for_seat_with_suffix() -> None:
    assert role_skill_for_seat('builder-1') == 'builder'
    assert role_skill_for_seat('reviewer-abc') == 'reviewer'
    assert role_skill_for_seat('patrol-42') == 'patrol'
    assert role_skill_for_seat('designer-main') == 'designer'
    assert role_skill_for_seat('unknown-role') == 'clawseat'
