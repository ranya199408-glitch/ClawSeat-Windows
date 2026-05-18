from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


def test_solo_b_planner_replacement() -> None:
    data = tomllib.loads(Path("templates/clawseat-solo.toml").read_text(encoding="utf-8"))
    ids = {e["id"] for e in data["engineers"]}
    assert "planner" in ids
    assert "designer" not in ids
    assert data["window_layout"]["workers_grid"]["right_seats"] == ["planner"]
    planner = next(e for e in data["engineers"] if e["id"] == "planner")
    assert planner["tool"] == "gemini"
    assert planner["auth_mode"] == "oauth"
    assert planner["provider"] == "google"
    assert planner["active_loop_owner"] is True
    mem = next(e for e in data["engineers"] if e["id"] == "memory")
    assert ("SWA" + "LLOW") not in " ".join(mem.get("role_details", []))
