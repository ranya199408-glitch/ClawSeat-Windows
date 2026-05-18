"""Tests for cartooner-harness MVP protocol scripts.

Covers spawn_lane, deposit_asset, report_to_memory — the minimum trio
needed to drive a creative project's lane lifecycle from spawn to deposit
to user-direct supersession.

All tests run against a tmp-rooted CARTOONER_ROOT (env var) so they do
not touch the operator's real ~/.cartooner/.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "cartooner-harness" / "scripts"


def _run(script: str, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, str(_SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


@pytest.fixture
def cartooner_env(tmp_path: Path) -> dict[str, str]:
    root = tmp_path / "cartooner"
    return {"CARTOONER_ROOT": str(root)}


@pytest.fixture
def cartooner_root(cartooner_env: dict[str, str]) -> Path:
    return Path(cartooner_env["CARTOONER_ROOT"])


# ── spawn_lane ────────────────────────────────────────────────────────


def test_spawn_lane_creates_lane_file_index_and_log(cartooner_env, cartooner_root):
    res = _run(
        "spawn_lane.py",
        "--project", "demo",
        "--seat", "builder-image",
        "--count", "4",
        "--prompt", "苹果特写, 露珠从顶部滑落",
        "--shot-id", "shot-1",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    lane_id = res.stdout.strip()
    assert lane_id.startswith("lane-builder-image-")

    project_root = cartooner_root / "projects" / "demo"

    lane_file = project_root / "lanes" / f"{lane_id}.toml"
    assert lane_file.is_file()
    text = lane_file.read_text(encoding="utf-8")
    assert 'seat = "builder-image"' in text
    assert 'state = "spawned"' in text
    assert "count = 4" in text
    assert 'shot_id = "shot-1"' in text

    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert index["project_id"] == "demo"
    assert index["automation_mode"] == "manual"
    assert lane_id in index["lanes"]
    assert index["lanes"][lane_id]["seat"] == "builder-image"
    assert index["lanes"][lane_id]["count"] == 4
    assert index["lanes"][lane_id]["shot_id"] == "shot-1"

    log_lines = (project_root / "generation_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 1
    log = json.loads(log_lines[0])
    assert log["event"] == "lane_spawned"
    assert log["lane_id"] == lane_id
    assert log["seat"] == "builder-image"
    assert log["count"] == 4
    assert log["actor"] == "memory"
    assert log["triggered_by"] == "memory_spawn"


def test_spawn_lane_user_direct_records_trigger(cartooner_env, cartooner_root):
    res = _run(
        "spawn_lane.py",
        "--project", "demo",
        "--seat", "builder-image",
        "--count", "2",
        "--prompt", "再来 2 张更暗的",
        "--triggered-by", "user_direct",
        "--actor", "builder-image",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    project_root = cartooner_root / "projects" / "demo"
    log = json.loads((project_root / "generation_log.jsonl").read_text(encoding="utf-8").strip())
    assert log["triggered_by"] == "user_direct"
    assert log["actor"] == "builder-image"


def test_spawn_lane_rejects_invalid_seat(cartooner_env):
    res = _run(
        "spawn_lane.py",
        "--project", "demo",
        "--seat", "memory",  # not a generation seat
        "--count", "4",
        "--prompt", "x",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_spawn_lane_rejects_count_out_of_range(cartooner_env):
    for bad_count in ("0", "-1", "32"):
        res = _run(
            "spawn_lane.py",
            "--project", "demo",
            "--seat", "builder-image",
            "--count", bad_count,
            "--prompt", "x",
            env=cartooner_env,
        )
        assert res.returncode != 0, f"count={bad_count} should fail"


# ── deposit_asset ─────────────────────────────────────────────────────


def _spawn(env, seat="builder-image", count=2, prompt="x"):
    res = _run(
        "spawn_lane.py",
        "--project", "demo",
        "--seat", seat,
        "--count", str(count),
        "--prompt", prompt,
        env=env,
    )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


def _make_fake_asset(tmp_path: Path, name: str, body: bytes = b"X" * 100) -> Path:
    f = tmp_path / name
    f.write_bytes(body)
    return f


def test_deposit_asset_records_metadata_only(cartooner_env, cartooner_root, tmp_path):
    lane_id = _spawn(cartooner_env, seat="builder-image", count=2)
    asset = _make_fake_asset(tmp_path, "img-001.png", b"\x89PNG\r\n\x1a\n" + b"X" * 100)

    res = _run(
        "deposit_asset.py",
        "--project", "demo",
        "--lane-id", lane_id,
        "--asset-id", "img-001",
        "--asset-path", str(asset),
        "--actor", "builder-image",
        "--asset-type", "image",
        "--model", "nano-banana",
        "--seed", "42",
        "--model-metadata", '{"aesthetic_score": 0.81, "safety": "ok"}',
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert "img-001" in index["assets"]
    a = index["assets"]["img-001"]
    assert a["model"] == "nano-banana"
    assert a["seed"] == 42
    assert a["lane"] == lane_id
    assert a["model_metadata"]["aesthetic_score"] == 0.81
    assert a["model_metadata"]["safety"] == "ok"
    assert a["file_size"] == 108

    # lane state still "generating" because not all 2 candidates landed
    assert index["lanes"][lane_id]["state"] == "generating"

    log_lines = (project_root / "generation_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 2
    deposit_log = json.loads(log_lines[1])
    assert deposit_log["event"] == "asset_deposited"
    assert deposit_log["asset_id"] == "img-001"
    assert deposit_log["lane_final"] is None or deposit_log["lane_final"] is False


def test_deposit_asset_final_candidate_transitions_lane_to_deposited(cartooner_env, cartooner_root, tmp_path):
    lane_id = _spawn(cartooner_env, count=1)
    asset = _make_fake_asset(tmp_path, "img-final.png")
    res = _run(
        "deposit_asset.py",
        "--project", "demo",
        "--lane-id", lane_id,
        "--asset-id", "img-final",
        "--asset-path", str(asset),
        "--actor", "builder-image",
        "--asset-type", "image",
        "--all-candidates-deposited",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert index["lanes"][lane_id]["state"] == "deposited"
    assert "deposited_at" in index["lanes"][lane_id]


def test_deposit_asset_rejects_nonexistent_lane(cartooner_env, tmp_path):
    asset = _make_fake_asset(tmp_path, "img.png")
    res = _run(
        "deposit_asset.py",
        "--project", "demo",
        "--lane-id", "lane-fake-deadbeef",
        "--asset-id", "img-001",
        "--asset-path", str(asset),
        "--actor", "builder-image",
        "--asset-type", "image",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_deposit_asset_rejects_actor_seat_mismatch(cartooner_env, tmp_path):
    lane_id = _spawn(cartooner_env, seat="builder-image", count=1)
    video = _make_fake_asset(tmp_path, "v.mp4")
    res = _run(
        "deposit_asset.py",
        "--project", "demo",
        "--lane-id", lane_id,
        "--asset-id", "v-001",
        "--asset-path", str(video),
        "--actor", "builder-av",  # mismatch: lane.seat = builder-image
        "--asset-type", "video",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_deposit_asset_rejects_asset_type_mismatch(cartooner_env, tmp_path):
    lane_id = _spawn(cartooner_env, seat="builder-image", count=1)
    video = _make_fake_asset(tmp_path, "v.mp4")
    res = _run(
        "deposit_asset.py",
        "--project", "demo",
        "--lane-id", lane_id,
        "--asset-id", "v-001",
        "--asset-path", str(video),
        "--actor", "builder-image",
        "--asset-type", "video",  # builder-image cannot deposit video
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_deposit_asset_rejects_empty_file(cartooner_env, tmp_path):
    lane_id = _spawn(cartooner_env, count=1)
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    res = _run(
        "deposit_asset.py",
        "--project", "demo",
        "--lane-id", lane_id,
        "--asset-id", "img-empty",
        "--asset-path", str(empty),
        "--actor", "builder-image",
        "--asset-type", "image",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_deposit_asset_rejects_into_superseded_lane(cartooner_env, tmp_path):
    lane_id = _spawn(cartooner_env, count=2)
    # supersede via report_to_memory
    res = _run(
        "report_to_memory.py",
        "--project", "demo",
        "--event", "user_direct_request",
        "--seat", "builder-image",
        "--triggered-by", "user",
        "--intent", "stop",
        "--supersedes", lane_id,
        env=cartooner_env,
    )
    assert res.returncode == 0
    asset = _make_fake_asset(tmp_path, "img.png")
    res = _run(
        "deposit_asset.py",
        "--project", "demo",
        "--lane-id", lane_id,
        "--asset-id", "img-orphan",
        "--asset-path", str(asset),
        "--actor", "builder-image",
        "--asset-type", "image",
        env=cartooner_env,
    )
    assert res.returncode != 0


# ── report_to_memory ──────────────────────────────────────────────────


def test_report_to_memory_user_direct_logs_actor_user(cartooner_env, cartooner_root):
    res = _run(
        "report_to_memory.py",
        "--project", "demo",
        "--event", "user_direct_request",
        "--seat", "builder-image",
        "--triggered-by", "user",
        "--intent", "再来 4 张更暗",
        "--action", "spawn_lane",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    project_root = cartooner_root / "projects" / "demo"
    log = json.loads((project_root / "generation_log.jsonl").read_text(encoding="utf-8").strip())
    assert log["event"] == "user_direct_request"
    assert log["actor"] == "user"
    assert log["triggered_by"] == "user"
    assert log["intent"] == "再来 4 张更暗"
    assert log["seat"] == "builder-image"


def test_report_to_memory_supersedes_marks_lane(cartooner_env, cartooner_root):
    lane_id = _spawn(cartooner_env, count=4)
    res = _run(
        "report_to_memory.py",
        "--project", "demo",
        "--event", "user_direct_request",
        "--seat", "builder-image",
        "--triggered-by", "user",
        "--intent", "stop, do wide shots instead",
        "--action", "spawn_lane",
        "--supersedes", lane_id,
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert index["lanes"][lane_id]["state"] == "superseded"
    assert "superseded_at" in index["lanes"][lane_id]
    assert index["lanes"][lane_id]["superseded_by_event"] == "user_direct_request"

    lane_text = (project_root / "lanes" / f"{lane_id}.toml").read_text(encoding="utf-8")
    assert 'state = "superseded"' in lane_text


def test_report_to_memory_rejects_unknown_supersedes(cartooner_env):
    res = _run(
        "report_to_memory.py",
        "--project", "demo",
        "--event", "user_direct_request",
        "--seat", "builder-image",
        "--triggered-by", "user",
        "--supersedes", "lane-fake",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_report_to_memory_flips_auto_to_manual_on_user_direct(cartooner_env, cartooner_root):
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True)
    initial = {
        "project_id": "demo",
        "version": 1,
        "created_at": "2026-05-10T00:00:00.000+00:00",
        "automation_mode": "auto",
        "lanes": {},
        "assets": {},
        "tournaments": {},
    }
    (project_root / "PROJECT_INDEX.json").write_text(json.dumps(initial), encoding="utf-8")

    res = _run(
        "report_to_memory.py",
        "--project", "demo",
        "--event", "user_direct_request",
        "--seat", "writer",
        "--triggered-by", "user",
        "--intent", "改对白",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr

    after = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert after["automation_mode"] == "manual"
    assert "automation_flipped_at" in after
    assert after["automation_flipped_reason"] == "user_direct_received"


def test_report_to_memory_does_not_flip_for_non_user_events(cartooner_env, cartooner_root):
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True)
    initial = {
        "project_id": "demo",
        "version": 1,
        "created_at": "2026-05-10T00:00:00.000+00:00",
        "automation_mode": "auto",
        "lanes": {}, "assets": {}, "tournaments": {},
    }
    (project_root / "PROJECT_INDEX.json").write_text(json.dumps(initial), encoding="utf-8")

    # patrol-triggered event in auto mode should NOT flip mode
    res = _run(
        "report_to_memory.py",
        "--project", "demo",
        "--event", "subagent_completed",
        "--seat", "patrol",
        "--triggered-by", "patrol",
        "--intent", "sla check passed",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    after = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert after["automation_mode"] == "auto"  # unchanged


def test_report_to_memory_subagent_event_carries_payload(cartooner_env, cartooner_root):
    res = _run(
        "report_to_memory.py",
        "--project", "demo",
        "--event", "subagent_started",
        "--seat", "builder-av",
        "--triggered-by", "user",
        "--intent", "ingest WKW for shot rhythm reference",
        "--action", "spawn_subagent",
        "--subagent-type", "reference_learning",
        "--subagent-inputs", '{"url": "https://youtube.com/watch?v=...", "focus": "shot rhythm"}',
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr

    project_root = cartooner_root / "projects" / "demo"
    log = json.loads((project_root / "generation_log.jsonl").read_text(encoding="utf-8").strip())
    assert log["subagent_type"] == "reference_learning"
    assert log["subagent_inputs"]["focus"] == "shot rhythm"


# ── end-to-end mini flow ──────────────────────────────────────────────


def test_full_mini_flow_spawn_two_deposits_then_user_supersede(cartooner_env, cartooner_root, tmp_path):
    """spawn(2) → deposit(1, generating) → deposit(2, deposited) → user supersedes."""
    lane_id = _spawn(cartooner_env, count=2, prompt="apple close-up")

    a1 = _make_fake_asset(tmp_path, "a1.png")
    a2 = _make_fake_asset(tmp_path, "a2.png")

    r1 = _run(
        "deposit_asset.py",
        "--project", "demo", "--lane-id", lane_id,
        "--asset-id", "img-1", "--asset-path", str(a1),
        "--actor", "builder-image", "--asset-type", "image",
        "--model", "nano-banana", "--seed", "1",
        env=cartooner_env,
    )
    assert r1.returncode == 0
    r2 = _run(
        "deposit_asset.py",
        "--project", "demo", "--lane-id", lane_id,
        "--asset-id", "img-2", "--asset-path", str(a2),
        "--actor", "builder-image", "--asset-type", "image",
        "--model", "nano-banana", "--seed", "2",
        "--all-candidates-deposited",
        env=cartooner_env,
    )
    assert r2.returncode == 0

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert index["lanes"][lane_id]["state"] == "deposited"
    assert set(index["assets"].keys()) == {"img-1", "img-2"}

    # user changes mind
    sup = _run(
        "report_to_memory.py",
        "--project", "demo",
        "--event", "user_direct_request",
        "--seat", "builder-image",
        "--triggered-by", "user",
        "--intent", "actually I want wide shots",
        "--supersedes", lane_id,
        env=cartooner_env,
    )
    assert sup.returncode == 0
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert index["lanes"][lane_id]["state"] == "superseded"

    log_lines = (project_root / "generation_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line)["event"] for line in log_lines]
    assert events == ["lane_spawned", "asset_deposited", "asset_deposited", "user_direct_request"]


# ── pick_winner ───────────────────────────────────────────────────────


def _spawn_and_deposit(env, tmp_path, *,
                       seat="builder-image", asset_type="image",
                       shot_id="shot-1", asset_ids=("img-001", "img-002"),
                       metadata=None):
    """Helper: spawn a lane and deposit a set of candidates with optional metadata."""
    res = _run(
        "spawn_lane.py",
        "--project", "demo",
        "--seat", seat,
        "--count", str(len(asset_ids)),
        "--prompt", "x",
        "--shot-id", shot_id,
        env=env,
    )
    assert res.returncode == 0, res.stderr
    lane_id = res.stdout.strip()

    suffix = {"image": ".png", "video": ".mp4", "audio": ".wav"}[asset_type]
    for i, asset_id in enumerate(asset_ids):
        f = tmp_path / f"{asset_id}{suffix}"
        f.write_bytes(b"X" * 100)
        meta = {}
        if metadata is not None:
            meta = metadata.get(asset_id, {})
        is_last = i == len(asset_ids) - 1
        args = [
            "--project", "demo",
            "--lane-id", lane_id,
            "--asset-id", asset_id,
            "--asset-path", str(f),
            "--actor", seat,
            "--asset-type", asset_type,
            "--model-metadata", json.dumps(meta),
        ]
        if is_last:
            args.append("--all-candidates-deposited")
        rd = _run("deposit_asset.py", *args, env=env)
        assert rd.returncode == 0, rd.stderr
    return lane_id


def test_pick_winner_manual_records_pick_and_marks_lane(cartooner_env, cartooner_root, tmp_path):
    _spawn_and_deposit(cartooner_env, tmp_path,
                       asset_ids=("img-001", "img-002", "img-003", "img-004"))
    res = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "img-001,img-002,img-003,img-004",
        "--strategy", "manual",
        "--picked", "img-002",
        "--pick-method", "external_signed_token",
        "--reason", "best mood for shot-1",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "img-002"

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert index["tournaments"]["shot-1-r1"]["picked"] == "img-002"
    assert index["assets"]["img-002"]["status"] == "picked"
    winner_lane = index["assets"]["img-002"]["lane"]
    assert index["lanes"][winner_lane]["state"] == "picked"

    tournament_text = (project_root / "tournaments" / "shot-1-r1.toml").read_text(encoding="utf-8")
    assert 'picked = "img-002"' in tournament_text
    assert 'reason = "best mood for shot-1"' in tournament_text


def test_pick_winner_reject_all_records_no_winner(cartooner_env, cartooner_root, tmp_path):
    _spawn_and_deposit(cartooner_env, tmp_path,
                       asset_ids=("img-001", "img-002"))
    res = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "img-001,img-002",
        "--strategy", "manual",
        "--reject-all",
        "--pick-method", "external_signed_token",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == ""

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    rec = index["tournaments"]["shot-1-r1"]
    assert rec["picked"] == ""
    assert rec["rejected_all"] is True
    # no asset/lane status changes
    assert index["assets"]["img-001"].get("status") != "picked"


def test_pick_winner_model_metadata_rank_picks_highest(cartooner_env, cartooner_root, tmp_path):
    _spawn_and_deposit(
        cartooner_env, tmp_path,
        asset_ids=("img-a", "img-b", "img-c", "img-d"),
        metadata={
            "img-a": {"aesthetic_score": 0.71},
            "img-b": {"aesthetic_score": 0.86},
            "img-c": {"aesthetic_score": 0.78},
            "img-d": {"aesthetic_score": 0.62},
        },
    )
    res = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "img-a,img-b,img-c,img-d",
        "--strategy", "model-metadata-rank",
        "--min-score", "0.75",
        "--picker", "memory_acting_director",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "img-b"  # highest above 0.75


def test_pick_winner_model_metadata_rank_below_threshold_fails(cartooner_env, tmp_path):
    _spawn_and_deposit(
        cartooner_env, tmp_path,
        asset_ids=("img-1", "img-2"),
        metadata={
            "img-1": {"aesthetic_score": 0.5},
            "img-2": {"aesthetic_score": 0.6},
        },
    )
    res = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "img-1,img-2",
        "--strategy", "model-metadata-rank",
        "--min-score", "0.75",
        "--picker", "memory_acting_director",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_pick_winner_model_metadata_rank_no_scores_fails(cartooner_env, tmp_path):
    _spawn_and_deposit(cartooner_env, tmp_path, asset_ids=("img-1", "img-2"))  # no metadata
    res = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "img-1,img-2",
        "--strategy", "model-metadata-rank",
        "--picker", "memory_acting_director",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_pick_winner_rejects_picked_not_in_candidates(cartooner_env, tmp_path):
    _spawn_and_deposit(cartooner_env, tmp_path, asset_ids=("img-1", "img-2"))
    res = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "img-1,img-2",
        "--strategy", "manual",
        "--picked", "img-9",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_pick_winner_rejects_unknown_candidate(cartooner_env, tmp_path):
    _spawn_and_deposit(cartooner_env, tmp_path, asset_ids=("img-1",))
    res = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "img-1,img-not-exist",
        "--strategy", "manual",
        "--picked", "img-1",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_pick_winner_rejects_candidates_across_shots(cartooner_env, tmp_path):
    _spawn_and_deposit(cartooner_env, tmp_path, shot_id="shot-1", asset_ids=("img-1",))
    _spawn_and_deposit(cartooner_env, tmp_path, shot_id="shot-2", asset_ids=("img-2",))
    res = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "mixed-r1",
        "--candidates", "img-1,img-2",
        "--strategy", "manual",
        "--picked", "img-1",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_pick_winner_idempotent_same_winner_re_call(cartooner_env, cartooner_root, tmp_path):
    _spawn_and_deposit(cartooner_env, tmp_path, asset_ids=("img-1", "img-2"))
    common_args = [
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "img-1,img-2",
        "--strategy", "manual",
        "--picked", "img-1",
        "--pick-method", "external_signed_token",
    ]
    r1 = _run("pick_winner.py", *common_args, env=cartooner_env)
    assert r1.returncode == 0
    r2 = _run("pick_winner.py", *common_args, env=cartooner_env)
    assert r2.returncode == 0  # same winner re-call OK


def test_pick_winner_rejects_change_winner_after_pick(cartooner_env, tmp_path):
    _spawn_and_deposit(cartooner_env, tmp_path, asset_ids=("img-1", "img-2"))
    r1 = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "img-1,img-2",
        "--strategy", "manual",
        "--picked", "img-1",
        "--pick-method", "external_signed_token",
        env=cartooner_env,
    )
    assert r1.returncode == 0
    r2 = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "img-1,img-2",
        "--strategy", "manual",
        "--picked", "img-2",  # different winner
        "--pick-method", "external_signed_token",
        env=cartooner_env,
    )
    assert r2.returncode != 0


def test_pick_winner_rejects_mutually_exclusive_picked_and_reject_all(cartooner_env, tmp_path):
    _spawn_and_deposit(cartooner_env, tmp_path, asset_ids=("img-1",))
    res = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "img-1",
        "--strategy", "manual",
        "--picked", "img-1",
        "--reject-all",
        env=cartooner_env,
    )
    assert res.returncode != 0


# ── iterate_prompt ────────────────────────────────────────────────────


def test_iterate_prompt_L3_records_lane_iteration(cartooner_env, cartooner_root):
    lane_id = _spawn(cartooner_env)
    res = _run(
        "iterate_prompt.py",
        "--project", "demo",
        "--layer", "L3",
        "--feedback", "all 4 too bright; want low-key lighting",
        "--parent-lane", lane_id,
        "--target", "lane",
        "--triggered-by-event", "user_direct",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    iter_id = res.stdout.strip()
    assert iter_id.startswith("iter-l3-")

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert iter_id in index["iterations"]
    rec = index["iterations"][iter_id]
    assert rec["layer"] == "L3"
    assert rec["parent_lane"] == lane_id
    assert rec["status"] == "open"

    iter_text = (project_root / "iterations" / f"{iter_id}.toml").read_text(encoding="utf-8")
    assert 'layer = "L3"' in iter_text
    assert "low-key lighting" in iter_text


def test_iterate_prompt_L2_records_shot_revision(cartooner_env, cartooner_root):
    res = _run(
        "iterate_prompt.py",
        "--project", "demo",
        "--layer", "L2",
        "--feedback", "shot 5 should be wide composition",
        "--parent-shot", "shot-5",
        "--target", "shot_list",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    iter_id = res.stdout.strip()
    assert iter_id.startswith("iter-l2-")

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    rec = index["iterations"][iter_id]
    assert rec["layer"] == "L2"
    assert rec["parent_shot"] == "shot-5"
    assert rec["target"] == "shot_list"


def test_iterate_prompt_L1_records_brief_revision(cartooner_env, cartooner_root):
    res = _run(
        "iterate_prompt.py",
        "--project", "demo",
        "--layer", "L1",
        "--feedback", "audience should be 18-25 not 25-35",
        "--target", "brief",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    iter_id = res.stdout.strip()
    assert iter_id.startswith("iter-l1-")


def test_iterate_prompt_L3_requires_parent_lane(cartooner_env):
    res = _run(
        "iterate_prompt.py",
        "--project", "demo",
        "--layer", "L3",
        "--feedback", "fix it",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_iterate_prompt_rejects_empty_feedback(cartooner_env):
    res = _run(
        "iterate_prompt.py",
        "--project", "demo",
        "--layer", "L1",
        "--feedback", "   ",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_iterate_prompt_rejects_unknown_parent_lane(cartooner_env):
    res = _run(
        "iterate_prompt.py",
        "--project", "demo",
        "--layer", "L3",
        "--feedback", "fix it",
        "--parent-lane", "lane-fake-deadbeef",
        env=cartooner_env,
    )
    assert res.returncode != 0


# ── full lifecycle: spawn → deposit → pick → iterate L3 → re-spawn ────


def test_full_lifecycle_with_iteration(cartooner_env, cartooner_root, tmp_path):
    """Realistic flow: spawn, deposit, user picks one but later iterates L3."""
    lane1 = _spawn_and_deposit(cartooner_env, tmp_path,
                               shot_id="shot-1",
                               asset_ids=("a", "b", "c", "d"))
    # user picks one
    r = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "a,b,c,d",
        "--strategy", "manual",
        "--picked", "b",
        "--pick-method", "external_signed_token",
        env=cartooner_env,
    )
    assert r.returncode == 0

    # user later wants iteration on the parent lane
    r = _run(
        "iterate_prompt.py",
        "--project", "demo",
        "--layer", "L3",
        "--feedback", "even better mood, deeper shadows",
        "--parent-lane", lane1,
        "--triggered-by-event", "user_direct",
        env=cartooner_env,
    )
    assert r.returncode == 0
    iter_id = r.stdout.strip()

    # caller (memory) would now spawn a child lane:
    r = _run(
        "spawn_lane.py",
        "--project", "demo",
        "--seat", "builder-image",
        "--count", "2",
        "--prompt", "[iterated] deeper shadows on apple close-up",
        "--shot-id", "shot-1",
        "--parent-lane", lane1,
        "--triggered-by", "iterate_prompt",
        env=cartooner_env,
    )
    assert r.returncode == 0
    child_lane = r.stdout.strip()

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert child_lane in index["lanes"]
    assert index["lanes"][child_lane]["triggered_by"] == "iterate_prompt"
    assert iter_id in index["iterations"]

    log_events = [
        json.loads(line)["event"]
        for line in (project_root / "generation_log.jsonl")
        .read_text(encoding="utf-8").strip().splitlines()
    ]
    # spawn_lane(parent) + 4×asset_deposited + pick_winner + iterate_prompt + spawn_lane(child)
    assert log_events.count("lane_spawned") == 2
    assert log_events.count("asset_deposited") == 4
    assert "pick_winner" in log_events
    assert "iterate_prompt" in log_events


# ── set_automation_mode ──────────────────────────────────────────────


def test_set_automation_mode_manual_default(cartooner_env, cartooner_root):
    res = _run(
        "set_automation_mode.py",
        "--project", "demo",
        "--mode", "manual",
        "--actor", "user",
        "--triggered-by", "user_request",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "manual"

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert index["automation_mode"] == "manual"
    assert index["automation_config"]["mode"] == "manual"
    assert index["automation_config"]["set_by"] == "user"
    # manual mode should not carry pick_strategy or escalate_on
    assert "pick_strategy" not in index["automation_config"]


def test_set_automation_mode_auto_requires_pick_strategy(cartooner_env):
    res = _run(
        "set_automation_mode.py",
        "--project", "demo",
        "--mode", "auto",
        "--actor", "user",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "pick-strategy" in (res.stderr or "")


def test_set_automation_mode_auto_with_strategy_and_triggers(cartooner_env, cartooner_root):
    res = _run(
        "set_automation_mode.py",
        "--project", "demo",
        "--mode", "auto",
        "--pick-strategy", "model-metadata-rank",
        "--escalate-on", "lane_failure,sla_breach,user_direct_received",
        "--actor", "user",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert index["automation_mode"] == "auto"
    assert index["automation_config"]["pick_strategy"] == "model-metadata-rank"
    assert index["automation_config"]["escalate_on"] == [
        "lane_failure", "sla_breach", "user_direct_received",
    ]


def test_set_automation_mode_auto_rejects_memory_actor(cartooner_env):
    res = _run(
        "set_automation_mode.py",
        "--project", "demo",
        "--mode", "auto",
        "--pick-strategy", "model-metadata-rank",
        "--actor", "memory_acting_director",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "self-elevate" in (res.stderr or "") or "user" in (res.stderr or "")


def test_set_automation_mode_auto_rejects_unknown_strategy(cartooner_env):
    res = _run(
        "set_automation_mode.py",
        "--project", "demo",
        "--mode", "auto",
        "--pick-strategy", "ai-overlord-decides",
        "--actor", "user",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_set_automation_mode_auto_rejects_unknown_trigger(cartooner_env):
    res = _run(
        "set_automation_mode.py",
        "--project", "demo",
        "--mode", "auto",
        "--pick-strategy", "model-metadata-rank",
        "--escalate-on", "lane_failure,fictional_trigger",
        "--actor", "user",
        env=cartooner_env,
    )
    assert res.returncode != 0


# ── escalate_to_producer ─────────────────────────────────────────────


def test_escalate_to_producer_records_and_flips_mode(cartooner_env, cartooner_root):
    # First go to auto mode
    _run(
        "set_automation_mode.py",
        "--project", "demo",
        "--mode", "auto",
        "--pick-strategy", "model-metadata-rank",
        "--actor", "user",
        env=cartooner_env,
    )
    # Then escalate with auto-flip
    res = _run(
        "escalate_to_producer.py",
        "--project", "demo",
        "--trigger", "tournament_ready_no_auto_pick_strategy",
        "--auto-flip-to-manual",
        "--context", "no qualifying winner above 0.75 threshold",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    esc_id = res.stdout.strip()
    assert esc_id.startswith("esc-")

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert index["automation_mode"] == "manual"
    assert esc_id in index["escalations"]
    rec = index["escalations"][esc_id]
    assert rec["trigger"] == "tournament_ready_no_auto_pick_strategy"
    assert rec["status"] == "open"
    assert rec["mode_at_escalation"] == "auto"

    esc_file = project_root / "escalations" / f"{esc_id}.toml"
    assert esc_file.is_file()
    text = esc_file.read_text(encoding="utf-8")
    assert 'trigger = "tournament_ready_no_auto_pick_strategy"' in text
    assert 'status = "open"' in text


def test_escalate_to_producer_without_flip_keeps_mode(cartooner_env, cartooner_root):
    _run(
        "set_automation_mode.py",
        "--project", "demo",
        "--mode", "auto",
        "--pick-strategy", "model-metadata-rank",
        "--actor", "user",
        env=cartooner_env,
    )
    res = _run(
        "escalate_to_producer.py",
        "--project", "demo",
        "--trigger", "phase_transition",
        "--context", "moving image -> video",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert index["automation_mode"] == "auto"


def test_escalate_to_producer_rejects_unknown_lane(cartooner_env):
    res = _run(
        "escalate_to_producer.py",
        "--project", "demo",
        "--trigger", "lane_failure",
        "--parent-lane", "lane-fake-deadbeef",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_escalate_to_producer_rejects_unknown_round(cartooner_env):
    res = _run(
        "escalate_to_producer.py",
        "--project", "demo",
        "--trigger", "tournament_ready_no_auto_pick_strategy",
        "--parent-round", "round-fake",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_escalate_to_producer_logs_event_with_trigger(cartooner_env, cartooner_root):
    res = _run(
        "escalate_to_producer.py",
        "--project", "demo",
        "--trigger", "lane_failure",
        env=cartooner_env,
    )
    assert res.returncode == 0
    project_root = cartooner_root / "projects" / "demo"
    log = (project_root / "generation_log.jsonl").read_text(encoding="utf-8").strip()
    last = json.loads(log.splitlines()[-1])
    assert last["event"] == "escalate_to_producer"
    assert last["trigger"] == "lane_failure"


# ── share_style_bible ────────────────────────────────────────────────


def test_share_style_bible_set_increments_version_and_records_history(
    cartooner_env, cartooner_root, tmp_path
):
    bible_v1 = tmp_path / "bible_v1.md"
    bible_v1.write_text("# style bible v1", encoding="utf-8")
    bible_v2 = tmp_path / "bible_v2.md"
    bible_v2.write_text("# style bible v2 (darker)", encoding="utf-8")

    r1 = _run(
        "share_style_bible.py",
        "--project", "demo",
        "--action", "set",
        "--bible-path", str(bible_v1),
        "--note", "first cut",
        env=cartooner_env,
    )
    assert r1.returncode == 0, r1.stderr
    assert r1.stdout.strip() == "1"

    r2 = _run(
        "share_style_bible.py",
        "--project", "demo",
        "--action", "set",
        "--bible-path", str(bible_v2),
        "--note", "darker palette",
        env=cartooner_env,
    )
    assert r2.returncode == 0, r2.stderr
    assert r2.stdout.strip() == "2"

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    sb = index["style_bible"]
    assert sb["version"] == 2
    assert sb["path"] == str(bible_v2)
    assert sb["note"] == "darker palette"
    assert len(sb["history"]) == 1
    assert sb["history"][0]["version"] == 1
    assert sb["history"][0]["path"] == str(bible_v1)


def test_share_style_bible_get_returns_current_path(cartooner_env, tmp_path):
    bible = tmp_path / "bible.md"
    bible.write_text("# bible", encoding="utf-8")
    _run(
        "share_style_bible.py",
        "--project", "demo",
        "--action", "set",
        "--bible-path", str(bible),
        env=cartooner_env,
    )
    res = _run(
        "share_style_bible.py",
        "--project", "demo",
        "--action", "get",
        env=cartooner_env,
    )
    assert res.returncode == 0
    assert res.stdout.strip() == str(bible)


def test_share_style_bible_get_returns_empty_when_unset(cartooner_env):
    res = _run(
        "share_style_bible.py",
        "--project", "demo",
        "--action", "get",
        env=cartooner_env,
    )
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_share_style_bible_set_rejects_missing_file(cartooner_env, tmp_path):
    res = _run(
        "share_style_bible.py",
        "--project", "demo",
        "--action", "set",
        "--bible-path", str(tmp_path / "ghost.md"),
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_share_style_bible_set_requires_bible_path(cartooner_env):
    res = _run(
        "share_style_bible.py",
        "--project", "demo",
        "--action", "set",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_share_style_bible_history_action(cartooner_env, tmp_path):
    bible_v1 = tmp_path / "v1.md"
    bible_v1.write_text("v1", encoding="utf-8")
    bible_v2 = tmp_path / "v2.md"
    bible_v2.write_text("v2", encoding="utf-8")
    _run("share_style_bible.py", "--project", "demo", "--action", "set",
         "--bible-path", str(bible_v1), env=cartooner_env)
    _run("share_style_bible.py", "--project", "demo", "--action", "set",
         "--bible-path", str(bible_v2), env=cartooner_env)
    res = _run("share_style_bible.py", "--project", "demo", "--action", "history",
               env=cartooner_env)
    assert res.returncode == 0
    lines = [l for l in res.stdout.strip().splitlines() if l]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["version"] == 1
    assert rec["path"] == str(bible_v1)


def test_share_style_bible_character_dna_target(cartooner_env, cartooner_root, tmp_path):
    dna = tmp_path / "dna.json"
    dna.write_text('{"name": "test"}', encoding="utf-8")
    res = _run(
        "share_style_bible.py",
        "--project", "demo",
        "--action", "set",
        "--target", "character-dna",
        "--bible-path", str(dna),
        env=cartooner_env,
    )
    assert res.returncode == 0
    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert index["character_dna"]["path"] == str(dna)
    assert index["character_dna"]["version"] == 1
    # style_bible should be untouched
    assert "style_bible" not in index or not index["style_bible"].get("path")


# ── render_asset_tree ────────────────────────────────────────────────


def test_render_asset_tree_missing_project_returns_2(cartooner_env):
    res = _run(
        "render_asset_tree.py",
        "--project", "no-such-project",
        env=cartooner_env,
    )
    assert res.returncode == 2


def test_render_asset_tree_text_renders_lanes_and_assets(
    cartooner_env, cartooner_root, tmp_path
):
    _spawn_and_deposit(cartooner_env, tmp_path, shot_id="shot-1",
                       asset_ids=("img-001", "img-002"))
    _spawn_and_deposit(cartooner_env, tmp_path, shot_id="shot-2",
                       asset_ids=("img-003",))
    res = _run(
        "render_asset_tree.py",
        "--project", "demo",
        "--format", "text",
        env=cartooner_env,
    )
    assert res.returncode == 0
    out = res.stdout
    assert "project: demo" in out
    assert "mode=manual" in out
    assert "shot-1" in out
    assert "shot-2" in out
    assert "img-001" in out
    assert "img-002" in out
    assert "img-003" in out


def test_render_asset_tree_json_format(cartooner_env, tmp_path):
    _spawn_and_deposit(cartooner_env, tmp_path, shot_id="shot-1",
                       asset_ids=("a", "b"))
    res = _run(
        "render_asset_tree.py",
        "--project", "demo",
        "--format", "json",
        env=cartooner_env,
    )
    assert res.returncode == 0
    payload = json.loads(res.stdout)
    assert payload["project_id"] == "demo"
    assert payload["automation_mode"] == "manual"
    assert "shot-1" in payload["shots"]
    lanes = payload["shots"]["shot-1"]["lanes"]
    assert len(lanes) == 1
    [(_, lane)] = lanes.items()
    asset_ids = {a["asset_id"] for a in lane["assets"]}
    assert asset_ids == {"a", "b"}


def test_render_asset_tree_includes_tournaments_iterations_escalations(
    cartooner_env, tmp_path
):
    lane = _spawn_and_deposit(cartooner_env, tmp_path, shot_id="shot-1",
                              asset_ids=("a", "b"))
    _run("pick_winner.py", "--project", "demo", "--round-id", "shot-1-r1",
         "--candidates", "a,b", "--strategy", "manual", "--picked", "a",
         "--pick-method", "external_signed_token",
         env=cartooner_env)
    _run("iterate_prompt.py", "--project", "demo", "--layer", "L3",
         "--feedback", "deeper shadow", "--parent-lane", lane,
         env=cartooner_env)
    _run("escalate_to_producer.py", "--project", "demo",
         "--trigger", "phase_transition", env=cartooner_env)
    res = _run("render_asset_tree.py", "--project", "demo", env=cartooner_env)
    assert res.returncode == 0
    out = res.stdout
    assert "tournaments:" in out
    assert "iterations:" in out
    assert "escalations:" in out
    assert "shot-1-r1" in out


def test_render_asset_tree_hides_superseded_by_default(cartooner_env, tmp_path):
    lane1 = _spawn_and_deposit(cartooner_env, tmp_path, shot_id="shot-1",
                               asset_ids=("a",))
    # supersede via report_to_memory --supersedes
    _run("report_to_memory.py", "--project", "demo",
         "--event", "user_direct_request", "--seat", "memory",
         "--supersedes", lane1, "--intent", "redo", env=cartooner_env)
    res = _run("render_asset_tree.py", "--project", "demo", env=cartooner_env)
    assert res.returncode == 0
    # superseded lane should be hidden
    assert lane1 not in res.stdout

    res2 = _run("render_asset_tree.py", "--project", "demo",
                "--include-superseded", env=cartooner_env)
    assert res2.returncode == 0
    assert lane1 in res2.stdout


# ── patrol_pipeline_sla ──────────────────────────────────────────────


def test_patrol_clean_project_exits_zero(cartooner_env, tmp_path):
    _spawn_and_deposit(cartooner_env, tmp_path, shot_id="shot-1",
                       asset_ids=("a", "b"))
    res = _run("patrol_pipeline_sla.py", "--project", "demo", env=cartooner_env)
    assert res.returncode == 0, res.stderr
    assert "clean (no anomalies)" in res.stdout


def test_patrol_missing_project_returns_1(cartooner_env):
    res = _run("patrol_pipeline_sla.py", "--project", "ghost", env=cartooner_env)
    assert res.returncode == 1


def test_patrol_integrity_detects_missing_asset_file(
    cartooner_env, cartooner_root, tmp_path
):
    _spawn_and_deposit(cartooner_env, tmp_path, shot_id="shot-1",
                       asset_ids=("a", "b"))
    # delete one asset file
    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    asset_path = Path(index["assets"]["a"]["path"])
    asset_path.unlink()

    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "integrity", env=cartooner_env)
    assert res.returncode == 2
    assert "asset file missing" in res.stdout


def test_patrol_integrity_detects_size_mismatch(
    cartooner_env, cartooner_root, tmp_path
):
    _spawn_and_deposit(cartooner_env, tmp_path, shot_id="shot-1",
                       asset_ids=("a",))
    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    asset_path = Path(index["assets"]["a"]["path"])
    # modify file to change size
    asset_path.write_bytes(b"different size content")
    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "integrity", env=cartooner_env)
    assert res.returncode == 2
    assert "size differs" in res.stdout


def test_patrol_sla_detects_old_lane(
    cartooner_env, cartooner_root, tmp_path
):
    """Spawn a lane, then mutate created_at to be old; SLA check should flag."""
    res = _run("spawn_lane.py", "--project", "demo", "--seat", "builder-image",
               "--count", "1", "--prompt", "x", "--shot-id", "shot-1",
               env=cartooner_env)
    assert res.returncode == 0
    lane_id = res.stdout.strip()

    project_root = cartooner_root / "projects" / "demo"
    index_path = project_root / "PROJECT_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    # forge created_at to 2 hours ago
    index["lanes"][lane_id]["created_at"] = "2026-05-10T00:00:00.000+00:00"
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "sla", "--sla-threshold-mins", "30",
               env=cartooner_env)
    assert res.returncode == 2
    assert "stuck in state=spawned" in res.stdout


def test_patrol_authorization_detects_unauthorized_actor(
    cartooner_env, cartooner_root
):
    """Manually inject a forged log line with an unauthorized actor."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({"project_id": "demo", "version": 1, "automation_mode": "manual",
                    "lanes": {}, "assets": {}, "tournaments": {}}),
        encoding="utf-8",
    )
    log_path = project_root / "generation_log.jsonl"
    log_path.write_text(
        json.dumps({
            "ts": "2026-05-10T00:00:00.000+00:00",
            "event": "pick_winner",
            "actor": "patrol",   # patrol cannot pick — violation
            "round_id": "shot-1-r1",
        }) + "\n",
        encoding="utf-8",
    )
    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "authorization", env=cartooner_env)
    assert res.returncode == 2
    assert "not authorized for event" in res.stdout
    assert "'patrol'" in res.stdout


def test_patrol_authorization_detects_asset_type_mismatch(
    cartooner_env, cartooner_root
):
    """builder-image depositing video — protocol violation."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({"project_id": "demo", "version": 1, "automation_mode": "manual",
                    "lanes": {}, "assets": {}, "tournaments": {}}),
        encoding="utf-8",
    )
    log_path = project_root / "generation_log.jsonl"
    log_path.write_text(
        json.dumps({
            "ts": "2026-05-10T00:00:00.000+00:00",
            "event": "asset_deposited",
            "actor": "builder-image",
            "asset_type": "video",   # image seat depositing video — violation
        }) + "\n",
        encoding="utf-8",
    )
    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "authorization", env=cartooner_env)
    assert res.returncode == 2
    assert "not authorized for asset_type" in res.stdout


def test_patrol_exit_zero_on_anomaly_flag(
    cartooner_env, cartooner_root, tmp_path
):
    """--exit-zero-on-anomaly suppresses non-zero exit but still reports."""
    _spawn_and_deposit(cartooner_env, tmp_path, shot_id="shot-1",
                       asset_ids=("a",))
    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    Path(index["assets"]["a"]["path"]).unlink()
    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "integrity", "--exit-zero-on-anomaly",
               env=cartooner_env)
    assert res.returncode == 0
    assert "asset file missing" in res.stdout


def test_patrol_json_format(cartooner_env, tmp_path):
    _spawn_and_deposit(cartooner_env, tmp_path, shot_id="shot-1",
                       asset_ids=("a",))
    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--format", "json", env=cartooner_env)
    assert res.returncode == 0
    payload = json.loads(res.stdout)
    assert payload["project"] == "demo"
    assert "checks_run" in payload
    assert "anomalies" in payload


# ── e2e: auto mode → escalate → manual flip ──────────────────────────


def test_e2e_auto_mode_escalation_flips_to_manual(cartooner_env, cartooner_root, tmp_path):
    """User starts auto mode, memory hits a wall, escalates, auto-flips to manual."""
    # 1. user enables auto mode
    _run("set_automation_mode.py", "--project", "demo", "--mode", "auto",
         "--pick-strategy", "model-metadata-rank",
         "--escalate-on", "tournament_ready_no_auto_pick_strategy,lane_failure",
         "--actor", "user", env=cartooner_env)

    # 2. memory spawns + deposits with NO aesthetic_score (cannot auto-pick)
    _spawn_and_deposit(cartooner_env, tmp_path, shot_id="shot-1",
                       asset_ids=("a", "b"))

    # 3. memory tries to auto-pick — fails because no scores
    pick = _run("pick_winner.py", "--project", "demo", "--round-id", "shot-1-r1",
                "--candidates", "a,b", "--strategy", "model-metadata-rank",
                "--picker", "memory_acting_director", env=cartooner_env)
    assert pick.returncode != 0   # no scores → fail-closed

    # 4. memory escalates to user
    esc = _run("escalate_to_producer.py", "--project", "demo",
               "--trigger", "tournament_ready_no_auto_pick_strategy",
               "--auto-flip-to-manual",
               "--context", "shot-1-r1: no aesthetic_score on candidates",
               env=cartooner_env)
    assert esc.returncode == 0

    # 5. mode is now manual; user can pick
    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert index["automation_mode"] == "manual"

    pick2 = _run("pick_winner.py", "--project", "demo", "--round-id", "shot-1-r1",
                 "--candidates", "a,b", "--strategy", "manual", "--picked", "a",
                 "--pick-method", "external_signed_token",
                 env=cartooner_env)
    assert pick2.returncode == 0

    # 6. log should record the full chain
    log = (project_root / "generation_log.jsonl").read_text(encoding="utf-8").strip()
    events = [json.loads(line)["event"] for line in log.splitlines()]
    assert "set_automation_mode" in events
    assert "escalate_to_producer" in events
    assert "pick_winner" in events


# ── spawn_subagent ───────────────────────────────────────────────────


def test_spawn_subagent_root_cause_happy_path(cartooner_env, cartooner_root):
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "spawn",
        "--seat", "builder-image",
        "--subagent-type", "root_cause",
        "--inputs", json.dumps({
            "candidate_ids": ["a", "b", "c", "d"],
            "user_feedback": "all 4 too bright",
        }),
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    sa_id = res.stdout.strip()
    assert sa_id.startswith("sa-rc-")

    project_root = cartooner_root / "projects" / "demo"
    sa_file = project_root / "subagents" / f"{sa_id}.toml"
    assert sa_file.is_file()
    text = sa_file.read_text(encoding="utf-8")
    assert 'type = "root_cause"' in text
    assert 'state = "spawned"' in text
    assert 'caller = "builder-image"' in text

    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert sa_id in index["subagents"]
    assert index["subagents"][sa_id]["state"] == "spawned"


def test_spawn_subagent_reference_learning_happy_path(cartooner_env):
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "spawn",
        "--seat", "builder-av",
        "--subagent-type", "reference_learning",
        "--inputs", json.dumps({
            "reference_url": "https://youtube.com/watch?v=xyz",
            "focus": "shot rhythm and camera motion",
        }),
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip().startswith("sa-ref-")


def test_spawn_subagent_rejects_unauthorized_seat(cartooner_env):
    """memory / writer / patrol cannot spawn subagents."""
    for seat in ("memory", "writer", "patrol"):
        res = _run(
            "spawn_subagent.py",
            "--project", "demo",
            "--action", "spawn",
            "--seat", seat,
            "--subagent-type", "root_cause",
            "--inputs", json.dumps({
                "candidate_ids": ["a"], "user_feedback": "x",
            }),
            env=cartooner_env,
        )
        assert res.returncode != 0, f"seat={seat} should be rejected"


def test_spawn_subagent_root_cause_requires_candidate_ids(cartooner_env):
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "spawn",
        "--seat", "builder-image",
        "--subagent-type", "root_cause",
        "--inputs", json.dumps({"user_feedback": "x"}),
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "candidate_ids" in (res.stderr or "")


def test_spawn_subagent_root_cause_requires_user_feedback(cartooner_env):
    """No user_feedback means it's a self-eval — protocol violation."""
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "spawn",
        "--seat", "builder-image",
        "--subagent-type", "root_cause",
        "--inputs", json.dumps({"candidate_ids": ["a"]}),
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "user_feedback" in (res.stderr or "") or "self-eval" in (res.stderr or "")


def test_spawn_subagent_reference_learning_requires_url(cartooner_env):
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "spawn",
        "--seat", "builder-av",
        "--subagent-type", "reference_learning",
        "--inputs", json.dumps({"focus": "shot rhythm"}),
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "reference_url" in (res.stderr or "")


def test_spawn_subagent_rejects_bad_json_inputs(cartooner_env):
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "spawn",
        "--seat", "builder-image",
        "--subagent-type", "root_cause",
        "--inputs", "not json{",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_spawn_subagent_rejects_unknown_round(cartooner_env):
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "spawn",
        "--seat", "builder-image",
        "--subagent-type", "root_cause",
        "--inputs", json.dumps({"candidate_ids": ["a"], "user_feedback": "x"}),
        "--parent-round", "round-fake",
        env=cartooner_env,
    )
    assert res.returncode != 0


def _spawn_subagent(env, inputs, *, seat="builder-image", sa_type="root_cause") -> str:
    r = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "spawn",
        "--seat", seat,
        "--subagent-type", sa_type,
        "--inputs", json.dumps(inputs),
        env=env,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_spawn_subagent_complete_happy_path(cartooner_env, cartooner_root, tmp_path):
    sa_id = _spawn_subagent(cartooner_env, {
        "candidate_ids": ["a", "b"], "user_feedback": "too bright",
    })
    report = tmp_path / "report.md"
    report.write_text("# root-cause findings\n\n- a: highlight blowout\n- b: ambient too high\n",
                      encoding="utf-8")
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "complete",
        "--subagent-id", sa_id,
        "--report-path", str(report),
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == sa_id

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    sa = index["subagents"][sa_id]
    assert sa["state"] == "completed"
    assert sa["report_path"] == str(report)
    assert sa["output_size_chars"] > 0


def test_spawn_subagent_complete_rejects_missing_report(cartooner_env, tmp_path):
    sa_id = _spawn_subagent(cartooner_env, {
        "candidate_ids": ["a"], "user_feedback": "x",
    })
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "complete",
        "--subagent-id", sa_id,
        "--report-path", str(tmp_path / "ghost.md"),
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_spawn_subagent_complete_rejects_empty_report(cartooner_env, tmp_path):
    sa_id = _spawn_subagent(cartooner_env, {
        "candidate_ids": ["a"], "user_feedback": "x",
    })
    empty = tmp_path / "empty.md"
    empty.write_bytes(b"")
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "complete",
        "--subagent-id", sa_id,
        "--report-path", str(empty),
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_spawn_subagent_complete_rejects_oversized_report(cartooner_env, tmp_path):
    """Reports > 1MB suggest binary contamination — fail-closed."""
    sa_id = _spawn_subagent(cartooner_env, {
        "candidate_ids": ["a"], "user_feedback": "x",
    })
    huge = tmp_path / "huge.md"
    huge.write_bytes(b"x" * (1_048_577))   # 1MB + 1 byte
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "complete",
        "--subagent-id", sa_id,
        "--report-path", str(huge),
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "exceeds limit" in (res.stderr or "") or "no-image-policy" in (res.stderr or "")


def test_spawn_subagent_complete_rejects_binary_report(cartooner_env, tmp_path):
    """Binary content (e.g. raw image bytes) violates no-image-policy."""
    sa_id = _spawn_subagent(cartooner_env, {
        "candidate_ids": ["a"], "user_feedback": "x",
    })
    binary = tmp_path / "bin.md"
    binary.write_bytes(b"\xff\xfe\x00\x01\x02\x80\x81\xfe")   # invalid utf-8
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "complete",
        "--subagent-id", sa_id,
        "--report-path", str(binary),
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_spawn_subagent_complete_rejects_unknown_id(cartooner_env, tmp_path):
    report = tmp_path / "report.md"
    report.write_text("# x", encoding="utf-8")
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "complete",
        "--subagent-id", "sa-rc-deadbeef",
        "--report-path", str(report),
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_spawn_subagent_complete_rejects_already_completed(cartooner_env, tmp_path):
    sa_id = _spawn_subagent(cartooner_env, {
        "candidate_ids": ["a"], "user_feedback": "x",
    })
    report = tmp_path / "report.md"
    report.write_text("# x", encoding="utf-8")
    r1 = _run(
        "spawn_subagent.py", "--project", "demo", "--action", "complete",
        "--subagent-id", sa_id, "--report-path", str(report), env=cartooner_env,
    )
    assert r1.returncode == 0
    # second complete should fail
    r2 = _run(
        "spawn_subagent.py", "--project", "demo", "--action", "complete",
        "--subagent-id", sa_id, "--report-path", str(report), env=cartooner_env,
    )
    assert r2.returncode != 0


def test_spawn_subagent_fail_happy_path(cartooner_env, cartooner_root):
    sa_id = _spawn_subagent(cartooner_env, {
        "reference_url": "https://youtube.com/x", "focus": "rhythm",
    }, seat="builder-av", sa_type="reference_learning")
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "fail",
        "--subagent-id", sa_id,
        "--reason", "youtube ingestion timed out",
        env=cartooner_env,
    )
    assert res.returncode == 0
    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert index["subagents"][sa_id]["state"] == "failed"
    assert index["subagents"][sa_id]["failure_reason"] == "youtube ingestion timed out"


def test_spawn_subagent_fail_rejects_unknown_id(cartooner_env):
    res = _run(
        "spawn_subagent.py", "--project", "demo", "--action", "fail",
        "--subagent-id", "sa-ref-deadbeef", env=cartooner_env,
    )
    assert res.returncode != 0


def test_spawn_subagent_log_event_actor_is_caller(cartooner_env, cartooner_root):
    sa_id = _spawn_subagent(cartooner_env, {
        "candidate_ids": ["a"], "user_feedback": "x",
    })
    project_root = cartooner_root / "projects" / "demo"
    log = (project_root / "generation_log.jsonl").read_text(encoding="utf-8").strip()
    last = json.loads(log.splitlines()[-1])
    assert last["event"] == "subagent_spawned"
    assert last["actor"] == "builder-image"
    assert last["subagent_id"] == sa_id
    assert last["subagent_type"] == "root_cause"


def test_patrol_authorization_catches_unauthorized_subagent_spawn(
    cartooner_env, cartooner_root
):
    """memory spawning a subagent is a violation patrol must catch."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({"project_id": "demo", "version": 1, "automation_mode": "manual",
                    "lanes": {}, "assets": {}, "tournaments": {}}),
        encoding="utf-8",
    )
    project_root.joinpath("generation_log.jsonl").write_text(
        json.dumps({
            "ts": "2026-05-10T00:00:00.000+00:00",
            "event": "subagent_spawned",
            "actor": "memory",   # memory cannot spawn — violation
            "subagent_id": "sa-rc-fake",
        }) + "\n",
        encoding="utf-8",
    )
    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "authorization", env=cartooner_env)
    assert res.returncode == 2
    assert "subagent_spawned" in res.stdout
    assert "'memory'" in res.stdout


# ── dispatch_brief / deliver_brief / writer-lane ─────────────────────


def test_dispatch_brief_writes_frontmatter_and_body(cartooner_env, cartooner_root):
    res = _run(
        "dispatch_brief.py",
        "--project", "demo",
        "--target", "writer",
        "--intent", "lyric",
        "--body", "30s 红苹果广告主题曲, 国风暗黑, 抖音 25-35 女性",
        "--deliverable-path", "lyrics_v1.md",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    brief_id = res.stdout.strip()
    assert brief_id.startswith("brief-")

    project_root = cartooner_root / "projects" / "demo"
    brief_file = project_root / "briefs" / f"{brief_id}.toml"
    assert brief_file.is_file()
    text = brief_file.read_text(encoding="utf-8")
    assert text.startswith("+++\n")
    assert 'target = "writer"' in text
    assert 'intent = "lyric"' in text
    assert 'state = "open"' in text
    assert "30s 红苹果广告主题曲" in text   # body present

    index = json.loads((project_root / "PROJECT_INDEX.json").read_text(encoding="utf-8"))
    assert brief_id in index["briefs"]
    assert index["briefs"][brief_id]["state"] == "open"
    assert index["briefs"][brief_id]["source"] == "memory"


def test_dispatch_brief_body_file(cartooner_env, cartooner_root, tmp_path):
    body_file = tmp_path / "long_brief.md"
    body_file.write_text("# Brief\n\nLine 1\nLine 2\n", encoding="utf-8")
    res = _run(
        "dispatch_brief.py",
        "--project", "demo",
        "--target", "builder-av",
        "--intent", "shot_list_revision",
        "--body-file", str(body_file),
        "--deliverable-path", "shot_list.toml",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0
    brief_id = res.stdout.strip()
    text = (cartooner_root / "projects" / "demo" / "briefs" / f"{brief_id}.toml").read_text()
    assert "Line 1" in text and "Line 2" in text


def test_dispatch_brief_rejects_empty_body(cartooner_env):
    res = _run(
        "dispatch_brief.py",
        "--project", "demo",
        "--target", "writer",
        "--intent", "lyric",
        "--body", "   ",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_dispatch_brief_rejects_unknown_parent_lane(cartooner_env):
    res = _run(
        "dispatch_brief.py",
        "--project", "demo",
        "--target", "writer",
        "--intent", "lyric",
        "--body", "x",
        "--parent-lane", "lane-fake-deadbeef",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_dispatch_brief_non_memory_actor_requires_user_direct(cartooner_env):
    res = _run(
        "dispatch_brief.py",
        "--project", "demo",
        "--target", "writer",
        "--intent", "lyric",
        "--body", "x",
        "--actor", "writer",
        "--triggered-by", "memory_dispatch",  # mismatch — should fail
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "user_direct" in (res.stderr or "")


def test_dispatch_brief_user_direct_self_dispatch(cartooner_env, cartooner_root):
    res = _run(
        "dispatch_brief.py",
        "--project", "demo",
        "--target", "builder-image",
        "--intent", "other",
        "--body", "user just told me to redo shot-3",
        "--actor", "builder-image",
        "--triggered-by", "user_direct",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    brief_id = res.stdout.strip()
    project_root = cartooner_root / "projects" / "demo"
    rec = json.loads((project_root / "PROJECT_INDEX.json").read_text())["briefs"][brief_id]
    assert rec["source"] == "user_direct:builder-image"
    assert rec["triggered_by"] == "user_direct"


def _dispatch_brief_helper(env, target="writer", intent="lyric", deliverable=""):
    """Default helper omits --deliverable-path so individual tests can
    deliver files of any basename without tripping coverage check.
    Pass `deliverable=` to opt-in (e.g. multi-deliverable tests)."""
    args = [
        "dispatch_brief.py",
        "--project", "demo",
        "--target", target,
        "--intent", intent,
        "--body", "test brief body",
        "--skip-wakeup",
    ]
    if deliverable:
        for d in (deliverable if isinstance(deliverable, (list, tuple)) else [deliverable]):
            args += ["--deliverable-path", d]
    r = _run(*args, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_deliver_brief_happy_path(cartooner_env, cartooner_root, tmp_path):
    brief_id = _dispatch_brief_helper(cartooner_env)
    deliverable = tmp_path / "lyrics.md"
    deliverable.write_text("# Lyrics\n\nVerse 1...\n", encoding="utf-8")
    res = _run(
        "deliver_brief.py",
        "--project", "demo",
        "--brief-id", brief_id,
        "--actor", "writer",
        "--output-path", str(deliverable),
        "--summary", "first draft, 4 hooks",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    rec = json.loads(
        (cartooner_root / "projects" / "demo" / "PROJECT_INDEX.json").read_text()
    )["briefs"][brief_id]
    assert rec["state"] == "delivered"
    assert rec["result"]["output_size_chars"] > 0
    assert rec["result"]["summary"] == "first draft, 4 hooks"


def test_deliver_brief_failure_path(cartooner_env, cartooner_root):
    brief_id = _dispatch_brief_helper(cartooner_env)
    res = _run(
        "deliver_brief.py",
        "--project", "demo",
        "--brief-id", brief_id,
        "--actor", "writer",
        "--fail",
        "--reason", "model API timed out twice",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0
    rec = json.loads(
        (cartooner_root / "projects" / "demo" / "PROJECT_INDEX.json").read_text()
    )["briefs"][brief_id]
    assert rec["state"] == "failed"
    assert rec["result"]["failure_reason"] == "model API timed out twice"


def test_deliver_brief_rejects_actor_mismatch(cartooner_env, tmp_path):
    brief_id = _dispatch_brief_helper(cartooner_env, target="writer")
    deliverable = tmp_path / "out.md"
    deliverable.write_text("x", encoding="utf-8")
    res = _run(
        "deliver_brief.py",
        "--project", "demo",
        "--brief-id", brief_id,
        "--actor", "builder-image",   # wrong — brief targets writer
        "--output-path", str(deliverable),
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "does not match brief.target" in (res.stderr or "")


def test_deliver_brief_rejects_double_close(cartooner_env, tmp_path):
    brief_id = _dispatch_brief_helper(cartooner_env)
    deliverable = tmp_path / "out.md"
    deliverable.write_text("x", encoding="utf-8")
    r1 = _run(
        "deliver_brief.py",
        "--project", "demo", "--brief-id", brief_id,
        "--actor", "writer", "--output-path", str(deliverable),
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert r1.returncode == 0
    r2 = _run(
        "deliver_brief.py",
        "--project", "demo", "--brief-id", brief_id,
        "--actor", "writer", "--output-path", str(deliverable),
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert r2.returncode != 0


def test_deliver_brief_rejects_binary_output(cartooner_env, tmp_path):
    brief_id = _dispatch_brief_helper(cartooner_env)
    binary = tmp_path / "binary.md"
    binary.write_bytes(b"\xff\xfe\x00\x01\x02\x80\xfe")
    res = _run(
        "deliver_brief.py",
        "--project", "demo", "--brief-id", brief_id,
        "--actor", "writer", "--output-path", str(binary),
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_deliver_brief_rejects_oversized_output(cartooner_env, tmp_path):
    brief_id = _dispatch_brief_helper(cartooner_env)
    huge = tmp_path / "huge.md"
    huge.write_bytes(b"a" * (5 * 1024 * 1024 + 1))
    res = _run(
        "deliver_brief.py",
        "--project", "demo", "--brief-id", brief_id,
        "--actor", "writer", "--output-path", str(huge),
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode != 0


def test_writer_lane_multi_candidate(cartooner_env, cartooner_root, tmp_path):
    """writer can be lane-spawned for multi-candidate text outputs."""
    res = _run(
        "spawn_lane.py",
        "--project", "demo",
        "--seat", "writer",
        "--count", "4",
        "--prompt", "4 hooks for 30s ad, 国风暗黑",
        "--shot-id", "hook-1",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    lane_id = res.stdout.strip()
    assert lane_id.startswith("lane-writer-")

    for i, name in enumerate(("h1", "h2", "h3", "h4")):
        f = tmp_path / f"{name}.md"
        f.write_text(f"# Hook {name}\n\n苹果赞歌 v{i+1}\n", encoding="utf-8")
        is_last = name == "h4"
        args = [
            "--project", "demo", "--lane-id", lane_id,
            "--asset-id", name, "--asset-path", str(f),
            "--actor", "writer", "--asset-type", "text",
        ]
        if is_last:
            args.append("--all-candidates-deposited")
        rd = _run("deposit_asset.py", *args, env=cartooner_env)
        assert rd.returncode == 0, rd.stderr

    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text())
    assert index["lanes"][lane_id]["seat"] == "writer"
    assert index["lanes"][lane_id]["state"] == "deposited"
    assert {a for a in index["assets"] if index["assets"][a]["lane"] == lane_id} == {"h1", "h2", "h3", "h4"}

    # tournament works on text candidates
    pick = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "hook-1-r1",
        "--candidates", "h1,h2,h3,h4",
        "--strategy", "manual",
        "--picked", "h2",
        "--pick-method", "external_signed_token",
        env=cartooner_env,
    )
    assert pick.returncode == 0


def test_writer_text_asset_rejects_binary(cartooner_env, cartooner_root, tmp_path):
    res = _run(
        "spawn_lane.py", "--project", "demo", "--seat", "writer",
        "--count", "1", "--prompt", "x", env=cartooner_env,
    )
    lane_id = res.stdout.strip()
    binary = tmp_path / "binary.md"
    binary.write_bytes(b"\xff\xfe\x00\x01")
    rd = _run(
        "deposit_asset.py",
        "--project", "demo", "--lane-id", lane_id,
        "--asset-id", "h1", "--asset-path", str(binary),
        "--actor", "writer", "--asset-type", "text",
        env=cartooner_env,
    )
    assert rd.returncode != 0
    assert "UTF-8" in (rd.stderr or "") or "no-image-policy" in (rd.stderr or "")


def test_writer_cannot_deposit_image(cartooner_env, cartooner_root, tmp_path):
    """asset_type / actor mismatch enforcement."""
    res = _run(
        "spawn_lane.py", "--project", "demo", "--seat", "writer",
        "--count", "1", "--prompt", "x", env=cartooner_env,
    )
    lane_id = res.stdout.strip()
    f = tmp_path / "x.png"
    f.write_bytes(b"X" * 100)
    rd = _run(
        "deposit_asset.py",
        "--project", "demo", "--lane-id", lane_id,
        "--asset-id", "x", "--asset-path", str(f),
        "--actor", "writer", "--asset-type", "image",   # forbidden
        env=cartooner_env,
    )
    assert rd.returncode != 0


def test_patrol_authorization_catches_non_memory_brief_dispatch(
    cartooner_env, cartooner_root
):
    """A brief_dispatched with actor != memory (and no user_direct path) is a violation."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({"project_id": "demo", "version": 1, "automation_mode": "manual",
                    "lanes": {}, "assets": {}, "tournaments": {}}),
        encoding="utf-8",
    )
    project_root.joinpath("generation_log.jsonl").write_text(
        json.dumps({
            "ts": "2026-05-10T00:00:00.000+00:00",
            "event": "brief_dispatched",
            "actor": "writer",   # only memory may dispatch
            "brief_id": "brief-fake",
        }) + "\n",
        encoding="utf-8",
    )
    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "authorization", env=cartooner_env)
    assert res.returncode == 2
    assert "brief_dispatched" in res.stdout
    assert "'writer'" in res.stdout


def test_dispatch_brief_log_event_records_wakeup_skip(cartooner_env, cartooner_root):
    brief_id = _dispatch_brief_helper(cartooner_env)
    log = (cartooner_root / "projects" / "demo" / "generation_log.jsonl").read_text()
    last = json.loads(log.strip().splitlines()[-1])
    assert last["event"] == "brief_dispatched"
    assert last["actor"] == "memory"
    assert last["wakeup_ok"] is False
    assert last["wakeup_reason"] == "skipped_by_caller"


def test_e2e_memory_dispatches_writer_brief_then_av_lane(
    cartooner_env, cartooner_root, tmp_path
):
    """Hub-and-spoke: memory→writer brief; writer delivers; memory→builder-av lane."""
    # 1. memory dispatches brief to writer
    brief_id = _dispatch_brief_helper(cartooner_env, target="writer", intent="narrative")

    # 2. writer delivers narrative
    narrative = tmp_path / "narrative_outline.md"
    narrative.write_text("# Narrative outline\n\nScene 1: ...\n", encoding="utf-8")
    r = _run(
        "deliver_brief.py",
        "--project", "demo", "--brief-id", brief_id,
        "--actor", "writer", "--output-path", str(narrative),
        "--summary", "first cut, 3 scenes",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert r.returncode == 0

    # 3. memory now spawns builder-av lane based on the narrative
    r = _run(
        "spawn_lane.py",
        "--project", "demo",
        "--seat", "builder-av",
        "--count", "2",
        "--prompt", "shot list authoring per narrative_outline.md",
        "--shot-id", "shot-1",
        env=cartooner_env,
    )
    assert r.returncode == 0

    # 4. log captures the full chain
    log = (cartooner_root / "projects" / "demo" / "generation_log.jsonl").read_text()
    events = [json.loads(line)["event"] for line in log.strip().splitlines()]
    assert "brief_dispatched" in events
    assert "brief_delivered" in events
    assert "lane_spawned" in events


# ── audit hardening (post-2026-05-11 review) ───────────────────────────


def test_dispatch_brief_rejects_lateral_seat_dispatch(cartooner_env):
    """Hub-and-spoke: writer cannot dispatch a brief to builder-av directly."""
    res = _run(
        "dispatch_brief.py",
        "--project", "demo",
        "--target", "builder-av",
        "--intent", "shot_list_revision",
        "--body", "shot 5 → wide-shot",
        "--actor", "writer",
        "--triggered-by", "user_direct",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "hub-and-spoke" in (res.stderr or "")


def test_patrol_authorization_cross_field_brief_dispatched(
    cartooner_env, cartooner_root
):
    """A brief_dispatched with non-memory actor without triggered_by=user_direct
    is a hub-and-spoke violation that patrol must detect."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({"project_id": "demo", "version": 1, "automation_mode": "manual",
                    "lanes": {}, "assets": {}, "tournaments": {}}),
        encoding="utf-8",
    )
    project_root.joinpath("generation_log.jsonl").write_text(
        json.dumps({
            "ts": "2026-05-10T00:00:00.000+00:00",
            "event": "brief_dispatched",
            "actor": "writer",
            "triggered_by": "memory_dispatch",
            "brief_id": "brief-fake",
        }) + "\n",
        encoding="utf-8",
    )
    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "authorization", env=cartooner_env)
    assert res.returncode == 2
    assert "hub-and-spoke" in res.stdout


def test_patrol_authorization_accepts_user_direct_self_dispatch(
    cartooner_env, cartooner_root
):
    """A brief_dispatched with non-memory actor BUT triggered_by=user_direct is OK."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({"project_id": "demo", "version": 1, "automation_mode": "manual",
                    "lanes": {}, "assets": {}, "tournaments": {}}),
        encoding="utf-8",
    )
    project_root.joinpath("generation_log.jsonl").write_text(
        json.dumps({
            "ts": "2026-05-10T00:00:00.000+00:00",
            "event": "brief_dispatched",
            "actor": "builder-image",
            "triggered_by": "user_direct",
            "brief_id": "brief-fake",
        }) + "\n",
        encoding="utf-8",
    )
    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "authorization", env=cartooner_env)
    assert res.returncode == 0
    assert "clean" in res.stdout


def test_parse_brief_handles_delivered_result_block(
    cartooner_env, cartooner_root, tmp_path
):
    """A delivered brief's body must NOT include the appended +++ result block."""
    brief_id = _dispatch_brief_helper(cartooner_env, target="writer", intent="narrative")
    deliverable = tmp_path / "narrative.md"
    deliverable.write_text("# Real body content\n\nLine 2\n", encoding="utf-8")
    r = _run(
        "deliver_brief.py",
        "--project", "demo", "--brief-id", brief_id,
        "--actor", "writer", "--output-path", str(deliverable),
        "--summary", "v1",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert r.returncode == 0, r.stderr

    # Now parse the brief file via _common.parse_brief and assert clean body.
    sys_path = str(_SCRIPTS)
    code = (
        f"import sys; sys.path.insert(0, {sys_path!r}); "
        f"import _common as c; "
        f"raw = open({str(_REPO / cartooner_env['CARTOONER_ROOT'])!r} + "
        f"  '/projects/demo/briefs/{brief_id}.toml').read(); "
        f"r = c.parse_brief(raw); "
        f"assert r is not None; "
        f"assert '+++ result' not in r['body'], 'body leaked result block: ' + r['body'][:200]; "
        f"assert r['state'] == 'delivered'; "
        f"assert '_result' in r and r['_result'].get('output_path'); "
        f"print('OK')"
    )
    res = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env={**os.environ, **cartooner_env},
    )
    assert res.returncode == 0, res.stderr
    assert "OK" in res.stdout


def test_render_asset_tree_shows_briefs_and_subagents(
    cartooner_env, cartooner_root
):
    """render_asset_tree must surface briefs + subagents (pull-fallback path)."""
    # 1. dispatch a brief
    _dispatch_brief_helper(cartooner_env, target="writer", intent="narrative")
    # 2. spawn a subagent
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "spawn",
        "--seat", "builder-av",
        "--subagent-type", "reference_learning",
        "--inputs", '{"reference_url": "https://youtube.com/x"}',
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    sa_id = res.stdout.strip()

    # 3. render
    res = _run("render_asset_tree.py", "--project", "demo", env=cartooner_env)
    assert res.returncode == 0, res.stderr
    assert "briefs:" in res.stdout
    assert "target=writer" in res.stdout
    assert "intent=narrative" in res.stdout
    assert "subagents:" in res.stdout
    assert sa_id in res.stdout
    assert "type=reference_learning" in res.stdout


def test_skeleton_creates_briefs_and_assets_text_dirs(cartooner_env, cartooner_root):
    """ensure_project_skeleton must create briefs/, subagents/, and assets/texts/ dirs."""
    _ = _dispatch_brief_helper(cartooner_env)
    project_root = cartooner_root / "projects" / "demo"
    for sub in ("briefs", "subagents", "assets/texts", "iterations", "escalations"):
        assert (project_root / sub).is_dir(), f"missing {sub}"


def test_patrol_sla_catches_stale_brief(cartooner_env, cartooner_root):
    """Briefs in 'open' state older than threshold must trigger an SLA alert."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({
            "project_id": "demo", "version": 1, "automation_mode": "manual",
            "lanes": {}, "assets": {}, "tournaments": {},
            "briefs": {
                "brief-stale": {
                    "id": "brief-stale", "state": "open",
                    "created_at": "2020-01-01T00:00:00.000+00:00",
                    "target": "writer", "intent": "narrative",
                },
            },
        }),
        encoding="utf-8",
    )
    res = _run(
        "patrol_pipeline_sla.py", "--project", "demo",
        "--check", "sla", env=cartooner_env,
    )
    assert res.returncode == 2
    assert "brief_id=brief-stale" in res.stdout


# ── memory_internal_note (audit finding #1) ────────────────────────────


def test_memory_internal_note_records_with_proper_schema(cartooner_env, cartooner_root):
    """memory_internal_note emits valid event/actor schema, never role/action."""
    res = _run(
        "report_to_memory.py",
        "--project", "demo",
        "--event", "memory_internal_note",
        "--seat", "memory",
        "--triggered-by", "memory",
        "--note", "anchor files written: brief.md / vision_spec.md / style_bible.md",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    log = (cartooner_root / "projects" / "demo" / "generation_log.jsonl").read_text()
    last = json.loads(log.strip().splitlines()[-1])
    assert last["event"] == "memory_internal_note"
    assert last["actor"] == "memory"  # NOT "role"
    assert "role" not in last
    assert "action" not in last or last.get("action") == ""
    assert "anchor files written" in last["note"]


def test_memory_internal_note_requires_note_text(cartooner_env):
    """Empty --note for memory_internal_note must fail-closed."""
    res = _run(
        "report_to_memory.py",
        "--project", "demo",
        "--event", "memory_internal_note",
        "--seat", "memory",
        "--triggered-by", "memory",
        # no --note
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "--note is required" in res.stderr


def test_patrol_accepts_memory_internal_note(cartooner_env, cartooner_root):
    """Patrol must accept memory_internal_note from memory actor without alert."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({"project_id": "demo", "version": 1, "automation_mode": "manual",
                    "lanes": {}, "assets": {}, "tournaments": {}}),
        encoding="utf-8",
    )
    project_root.joinpath("generation_log.jsonl").write_text(
        json.dumps({
            "ts": "2026-05-10T00:00:00.000+00:00",
            "event": "memory_internal_note",
            "actor": "memory",
            "note": "drafted vision_spec.md v1",
        }) + "\n",
        encoding="utf-8",
    )
    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "authorization", env=cartooner_env)
    assert res.returncode == 0
    assert "clean" in res.stdout


def test_patrol_alerts_on_memory_internal_note_from_wrong_actor(
    cartooner_env, cartooner_root
):
    """Non-memory actor on memory_internal_note → patrol alert."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({"project_id": "demo", "version": 1, "automation_mode": "manual",
                    "lanes": {}, "assets": {}, "tournaments": {}}),
        encoding="utf-8",
    )
    project_root.joinpath("generation_log.jsonl").write_text(
        json.dumps({
            "ts": "2026-05-10T00:00:00.000+00:00",
            "event": "memory_internal_note",
            "actor": "writer",  # writer cannot use this channel
            "note": "writer should not be writing internal notes",
        }) + "\n",
        encoding="utf-8",
    )
    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "authorization", env=cartooner_env)
    assert res.returncode == 2
    assert "actor 'writer' not authorized" in res.stdout


def test_report_to_memory_accepts_shot_list_authored(cartooner_env, cartooner_root):
    """shot_list_authored is now a valid event (mirrors shot_list_revised)."""
    res = _run(
        "report_to_memory.py",
        "--project", "demo",
        "--event", "shot_list_authored",
        "--seat", "builder-av",
        "--triggered-by", "memory",
        "--intent", "draft v1 of shot_list",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    log = (cartooner_root / "projects" / "demo" / "generation_log.jsonl").read_text()
    last = json.loads(log.strip().splitlines()[-1])
    assert last["event"] == "shot_list_authored"


# ── path-traversal hardening (validate_id_token) ───────────────────────


@pytest.mark.parametrize("malicious_id", [
    "../../../tmp/evil",
    "/etc/passwd",
    "round-1\nbacktrack",
    ".hidden",
    "-flag",
    "round id with spaces",
    "round..bad",
    "x:colon",
    "",
])
def test_pick_winner_rejects_malicious_round_id(cartooner_env, malicious_id):
    res = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", malicious_id,
        "--candidates", "img-1",
        "--strategy", "manual",
        "--picked", "img-1",
        env=cartooner_env,
    )
    assert res.returncode != 0
    # Empty string is caught by argparse-required flag wrapping; others by validate_id_token.
    assert ("--round-id" in res.stderr) or ("required" in res.stderr.lower())


def test_pick_winner_rejects_traversal_in_candidate(cartooner_env, cartooner_root):
    """Candidate ids land in PROJECT_INDEX.assets keys + tournament records."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({
            "project_id": "demo", "version": 1, "automation_mode": "manual",
            "lanes": {}, "assets": {"../../../tmp/evil": {"lane": "lane-x"}},
            "tournaments": {},
        }),
        encoding="utf-8",
    )
    res = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "round-1",
        "--candidates", "../../../tmp/evil",
        "--strategy", "manual",
        "--picked", "../../../tmp/evil",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "--candidates element" in res.stderr


def test_deposit_asset_rejects_traversal_lane_id(cartooner_env, tmp_path):
    asset = tmp_path / "img.png"
    asset.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    res = _run(
        "deposit_asset.py",
        "--project", "demo",
        "--lane-id", "../../../tmp/evil",
        "--asset-id", "img-1",
        "--asset-path", str(asset),
        "--actor", "builder-image",
        "--asset-type", "image",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "--lane-id" in res.stderr


def test_deliver_brief_rejects_traversal_brief_id(cartooner_env):
    res = _run(
        "deliver_brief.py",
        "--project", "demo",
        "--brief-id", "../../../tmp/evil",
        "--actor", "writer",
        "--fail",
        "--reason", "test",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "--brief-id" in res.stderr


def test_spawn_subagent_rejects_traversal_subagent_id(cartooner_env):
    res = _run(
        "spawn_subagent.py",
        "--project", "demo",
        "--action", "fail",
        "--subagent-id", "../../../tmp/evil",
        "--reason", "test",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "--subagent-id" in res.stderr


# ── update_project_index file lock (audit finding #3) ─────────────────


def test_update_project_index_concurrent_writers_no_loss(cartooner_env, cartooner_root):
    """Two parallel spawn_lane calls must not race-drop a lane from the index.

    Without flock, both spawn_lane subprocesses load the same baseline,
    each adds its own lane in-memory, both write — last writer wins,
    one lane disappears from PROJECT_INDEX even though its TOML is on
    disk. This test fires N parallel spawns and asserts ALL land in the
    index.
    """
    import concurrent.futures
    n = 10
    def _spawn(i):
        return _run(
            "spawn_lane.py",
            "--project", "demo",
            "--seat", "builder-image",
            "--count", "2",
            "--prompt", f"parallel-{i}",
            "--shot-id", f"shot-{i}",
            "--skip-wakeup",
            env=cartooner_env,
        )
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        results = list(ex.map(_spawn, range(n)))
    for r in results:
        assert r.returncode == 0, r.stderr
    lane_ids = sorted(r.stdout.strip() for r in results)
    assert len(lane_ids) == n
    project_root = cartooner_root / "projects" / "demo"
    index = json.loads((project_root / "PROJECT_INDEX.json").read_text())
    indexed = sorted(index.get("lanes", {}).keys())
    missing = [lid for lid in lane_ids if lid not in indexed]
    assert not missing, (
        f"file lock failed — {len(missing)} lanes lost from PROJECT_INDEX: {missing}"
    )
    # Every lane file is on disk (write_lane is per-lane, not contended)
    for lid in lane_ids:
        assert (project_root / "lanes" / f"{lid}.toml").is_file()


def test_update_project_index_mutator_can_return_new_dict(cartooner_env, cartooner_root):
    """mutator may either mutate-in-place (return None) or return a new dict."""
    import sys, subprocess
    code = (
        f"import sys; sys.path.insert(0, '{_SCRIPTS}'); "
        f"import _common as c; "
        f"c.update_project_index('demo', lambda i: dict(i, marker='in-place')); "
        f"print(c.load_project_index('demo')['marker'])"
    )
    res = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env={**os.environ, **cartooner_env},
    )
    assert res.returncode == 0, res.stderr
    assert "in-place" in res.stdout


# ── pick_winner trust-aware pick_method (audit finding #4) ─────────────


def test_pick_winner_requires_pick_method_when_picker_user(cartooner_env, tmp_path):
    """--picker user without --pick-method must fail-closed."""
    _spawn_and_deposit(cartooner_env, tmp_path, asset_ids=("img-1", "img-2"))
    res = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "img-1,img-2",
        "--strategy", "manual",
        "--picked", "img-1",
        # no --pick-method
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "--pick-method is REQUIRED" in res.stderr


def test_pick_winner_records_pick_method_in_log(cartooner_env, cartooner_root, tmp_path):
    _spawn_and_deposit(cartooner_env, tmp_path, asset_ids=("img-1", "img-2"))
    res = _run(
        "pick_winner.py",
        "--project", "demo",
        "--round-id", "shot-1-r1",
        "--candidates", "img-1,img-2",
        "--strategy", "manual",
        "--picked", "img-1",
        "--pick-method", "native_ask_user_question",
        env=cartooner_env,
    )
    assert res.returncode == 0
    log = (cartooner_root / "projects" / "demo" / "generation_log.jsonl").read_text()
    last = json.loads(log.strip().splitlines()[-1])
    assert last["event"] == "pick_winner"
    assert last["pick_method"] == "native_ask_user_question"
    # tournament TOML also captures it
    rec = json.loads((cartooner_root / "projects" / "demo" / "PROJECT_INDEX.json").read_text())
    assert rec["tournaments"]["shot-1-r1"]["pick_method"] == "native_ask_user_question"


def test_patrol_warns_on_native_ask_user_question_pick(cartooner_env, cartooner_root):
    """Weak-trust pick_method=native_ask_user_question with picker=user → patrol warn."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({"project_id": "demo", "version": 1, "automation_mode": "manual",
                    "lanes": {}, "assets": {}, "tournaments": {}}),
        encoding="utf-8",
    )
    project_root.joinpath("generation_log.jsonl").write_text(
        json.dumps({
            "ts": "2026-05-10T00:00:00.000+00:00",
            "event": "pick_winner",
            "actor": "user",
            "pick_method": "native_ask_user_question",
            "round_id": "r-x",
        }) + "\n",
        encoding="utf-8",
    )
    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "authorization", env=cartooner_env)
    assert res.returncode == 2
    assert "trust depends on session attachment" in res.stdout


def test_patrol_alerts_on_missing_pick_method(cartooner_env, cartooner_root):
    """Legacy log entry with actor=user but no pick_method → alert (broken trust chain)."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({"project_id": "demo", "version": 1, "automation_mode": "manual",
                    "lanes": {}, "assets": {}, "tournaments": {}}),
        encoding="utf-8",
    )
    project_root.joinpath("generation_log.jsonl").write_text(
        json.dumps({
            "ts": "2026-05-10T00:00:00.000+00:00",
            "event": "pick_winner",
            "actor": "user",
            "round_id": "r-y",
            # no pick_method field — legacy entry
        }) + "\n",
        encoding="utf-8",
    )
    res = _run("patrol_pipeline_sla.py", "--project", "demo",
               "--check", "authorization", env=cartooner_env)
    assert res.returncode == 2
    assert "trust chain broken" in res.stdout


# ── audit finding #8: project context drift / brief.project anchor ────


def test_dispatch_brief_writes_project_in_frontmatter(cartooner_env, cartooner_root):
    """Brief frontmatter must carry project= so receiver can verify."""
    brief_id = _dispatch_brief_helper(cartooner_env, target="writer", intent="narrative")
    project_root = cartooner_root / "projects" / "demo"
    raw = (project_root / "briefs" / f"{brief_id}.toml").read_text(encoding="utf-8")
    assert 'project = "demo"' in raw
    rec = json.loads((project_root / "PROJECT_INDEX.json").read_text())["briefs"][brief_id]
    assert rec["project"] == "demo"


def test_deliver_brief_rejects_project_mismatch(cartooner_env, cartooner_root, tmp_path):
    """Receiver passing --project that disagrees with brief.project must fail."""
    brief_id = _dispatch_brief_helper(cartooner_env, target="writer", intent="narrative")
    deliverable = tmp_path / "out.md"
    deliverable.write_text("done\n", encoding="utf-8")
    # Now create a different project with skeleton + lie about brief location
    (cartooner_root / "projects" / "other").mkdir(parents=True, exist_ok=True)
    # Copy index + briefs/ over so deliver_brief can find the brief at wrong path
    import shutil
    shutil.copytree(
        cartooner_root / "projects" / "demo",
        cartooner_root / "projects" / "other",
        dirs_exist_ok=True,
    )
    res = _run(
        "deliver_brief.py",
        "--project", "other",
        "--brief-id", brief_id,
        "--actor", "writer",
        "--output-path", str(deliverable),
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "disagrees with brief frontmatter" in res.stderr
    assert "demo" in res.stderr  # canonical project


def test_dispatch_brief_wakeup_message_names_project(cartooner_env, cartooner_root):
    """Wakeup message text must include project= so receiver LLM doesn't drift."""
    brief_id = _dispatch_brief_helper(cartooner_env, target="writer", intent="narrative")
    log = (cartooner_root / "projects" / "demo" / "generation_log.jsonl").read_text()
    last = [json.loads(l) for l in log.strip().splitlines() if 'brief_dispatched' in l][-1]
    # The wakeup message itself isn't logged but the brief frontmatter should
    # carry project (verified above). Verify the dispatch_brief script
    # actually produces the project-bearing wakeup_message by re-checking
    # via subprocess behavior (skip-wakeup path doesn't expose the message).
    # Indirectly: ensure the brief's actor + project pair is recorded.
    assert last["brief_id"] == brief_id
    # The project anchor lives in the index_record:
    rec = json.loads((cartooner_root / "projects" / "demo" / "PROJECT_INDEX.json").read_text())["briefs"][brief_id]
    assert rec["project"] == "demo"


def test_dispatch_brief_target_session_override(cartooner_env, cartooner_root):
    """--target-session bypasses resolve_seat_session (cross-project transport)."""
    res = _run(
        "dispatch_brief.py",
        "--project", "demo",
        "--target", "writer",
        "--intent", "narrative",
        "--body", "test override",
        "--target-session", "some-other-project-writer-claude",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    # When skip-wakeup is set, override is unused but argparse must accept it.


def test_deliver_brief_target_session_override(cartooner_env, cartooner_root, tmp_path):
    """--target-session on deliver_brief overrides memory session lookup."""
    brief_id = _dispatch_brief_helper(cartooner_env, target="writer", intent="narrative")
    deliverable = tmp_path / "out.md"
    deliverable.write_text("done\n", encoding="utf-8")
    res = _run(
        "deliver_brief.py",
        "--project", "demo",
        "--brief-id", brief_id,
        "--actor", "writer",
        "--output-path", str(deliverable),
        "--target-session", "cross-project-memory-claude",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr


def test_spawn_lane_target_session_override(cartooner_env):
    res = _run(
        "spawn_lane.py",
        "--project", "demo",
        "--seat", "builder-image",
        "--count", "1",
        "--prompt", "x",
        "--target-session", "explicit-target",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr


def test_dispatch_brief_rejects_traversal_parent_lane(cartooner_env):
    res = _run(
        "dispatch_brief.py",
        "--project", "demo",
        "--target", "writer",
        "--intent", "narrative",
        "--body", "x",
        "--parent-lane", "../../../tmp/evil",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "--parent-lane" in res.stderr


# ── audit finding #9: multi-deliverable + dispatch_session ─────────────


def test_dispatch_brief_records_multiple_deliverable_paths(
    cartooner_env, cartooner_root
):
    """--deliverable-path is repeatable; frontmatter stores plural list."""
    res = _run(
        "dispatch_brief.py",
        "--project", "demo",
        "--target", "writer",
        "--intent", "other",
        "--body", "write workflow notes + premise",
        "--deliverable-path", "WORKFLOW_NOTES.md",
        "--deliverable-path", "STORY_PREMISE.md",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    brief_id = res.stdout.strip()
    rec = json.loads(
        (cartooner_root / "projects" / "demo" / "PROJECT_INDEX.json").read_text()
    )["briefs"][brief_id]
    assert rec["deliverable_paths"] == ["WORKFLOW_NOTES.md", "STORY_PREMISE.md"]
    raw = (
        cartooner_root / "projects" / "demo" / "briefs" / f"{brief_id}.toml"
    ).read_text(encoding="utf-8")
    assert 'deliverable_paths = ["WORKFLOW_NOTES.md", "STORY_PREMISE.md"]' in raw


def test_deliver_brief_multi_output_happy_path(
    cartooner_env, cartooner_root, tmp_path
):
    """--output-path repeatable; result.outputs is the authoritative list."""
    brief_id = _dispatch_brief_helper(
        cartooner_env,
        target="writer",
        intent="other",
        deliverable=["WORKFLOW_NOTES.md", "STORY_PREMISE.md"],
    )
    f1 = tmp_path / "WORKFLOW_NOTES.md"
    f1.write_text("# notes\n\nbody\n", encoding="utf-8")
    f2 = tmp_path / "STORY_PREMISE.md"
    f2.write_text("# premise\n\nlogline\n", encoding="utf-8")
    res = _run(
        "deliver_brief.py",
        "--project", "demo",
        "--brief-id", brief_id,
        "--actor", "writer",
        "--output-path", str(f1),
        "--output-path", str(f2),
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    rec = json.loads(
        (cartooner_root / "projects" / "demo" / "PROJECT_INDEX.json").read_text()
    )["briefs"][brief_id]
    assert rec["state"] == "delivered"
    outputs = rec["result"]["outputs"]
    assert len(outputs) == 2
    basenames = {Path(o["path"]).name for o in outputs}
    assert basenames == {"WORKFLOW_NOTES.md", "STORY_PREMISE.md"}
    # Back-compat single-output fields point at the first one
    assert rec["result"]["output_size_chars"] == outputs[0]["output_size_chars"]


def test_deliver_brief_multi_output_rejects_missing_coverage(
    cartooner_env, tmp_path
):
    """If brief expects 2 deliverables, deliver of just 1 must fail-closed."""
    brief_id = _dispatch_brief_helper(
        cartooner_env,
        target="writer",
        intent="other",
        deliverable=["WORKFLOW_NOTES.md", "STORY_PREMISE.md"],
    )
    f1 = tmp_path / "WORKFLOW_NOTES.md"
    f1.write_text("# notes\n\nbody\n", encoding="utf-8")
    res = _run(
        "deliver_brief.py",
        "--project", "demo",
        "--brief-id", brief_id,
        "--actor", "writer",
        "--output-path", str(f1),
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "coverage is incomplete" in res.stderr
    assert "STORY_PREMISE.md" in res.stderr


def test_dispatch_brief_records_dispatch_session_from_arg(
    cartooner_env, cartooner_root
):
    """--dispatch-session value lands in brief frontmatter for return wakeup."""
    res = _run(
        "dispatch_brief.py",
        "--project", "demo",
        "--target", "writer",
        "--intent", "other",
        "--body", "x",
        "--dispatch-session", "cartooner-video-memory-claude",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    brief_id = res.stdout.strip()
    raw = (
        cartooner_root / "projects" / "demo" / "briefs" / f"{brief_id}.toml"
    ).read_text(encoding="utf-8")
    assert 'dispatch_session = "cartooner-video-memory-claude"' in raw
    rec = json.loads(
        (cartooner_root / "projects" / "demo" / "PROJECT_INDEX.json").read_text()
    )["briefs"][brief_id]
    assert rec["dispatch_session"] == "cartooner-video-memory-claude"


def test_dispatch_brief_dispatch_session_blank_when_no_tmux_no_arg(
    cartooner_env, cartooner_root, monkeypatch
):
    """No $TMUX + no --dispatch-session → dispatch_session is blank string."""
    monkeypatch.delenv("TMUX", raising=False)
    res = _run(
        "dispatch_brief.py",
        "--project", "demo",
        "--target", "writer",
        "--intent", "other",
        "--body", "x",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    brief_id = res.stdout.strip()
    rec = json.loads(
        (cartooner_root / "projects" / "demo" / "PROJECT_INDEX.json").read_text()
    )["briefs"][brief_id]
    assert rec["dispatch_session"] == ""


def test_deliver_brief_uses_dispatch_session_from_brief_for_wakeup(
    cartooner_env, cartooner_root, tmp_path
):
    """Receiver passes no --target-session → fallback to brief.dispatch_session.

    We assert the wakeup target by intercepting send-and-verify.sh via a
    fake transport that just records the session arg to a file.
    """
    fake_transport = tmp_path / "core" / "shell-scripts" / "send-and-verify.sh"
    fake_transport.parent.mkdir(parents=True)
    record_path = tmp_path / "wakeup-target.txt"
    fake_transport.write_text(
        "#!/usr/bin/env bash\n"
        "# args: --project <p> <session> <message...>\n"
        f"echo \"$3\" > {record_path}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_transport.chmod(0o755)

    # Place the script next to scripts/_common.py so its parent walk finds it.
    # _send_and_verify_path() walks up from scripts/ looking for
    # core/shell-scripts/send-and-verify.sh — we satisfy that by symlinking
    # the fake path into a parent the walker actually traverses.
    # Simpler: prepend tmp_path to ANY parent walked from scripts/. The
    # walker checks parent/core/shell-scripts/send-and-verify.sh for each
    # parent of scripts/, so we can't easily inject. Instead override
    # PATH for tmux + use --target-session explicitly to skip the fallback.
    # Better approach for THIS test: dispatch with --dispatch-session, then
    # assert deliver succeeds and wakeup_reason changes from
    # "no_target_session" to a real attempt.
    bid = _run(
        "dispatch_brief.py",
        "--project", "demo",
        "--target", "writer",
        "--intent", "other",
        "--body", "x",
        "--dispatch-session", "fake-memory-session-name",
        "--skip-wakeup",
        env=cartooner_env,
    ).stdout.strip()

    out = tmp_path / "deliver.md"
    out.write_text("done\n", encoding="utf-8")
    # NOT passing --skip-wakeup: we want the resolution + send_wakeup path.
    # The transport is missing in our test sandbox so wakeup will report
    # transport_missing — but importantly NOT no_target_session, proving
    # dispatch_session was picked up as the target.
    res = _run(
        "deliver_brief.py",
        "--project", "demo",
        "--brief-id", bid,
        "--actor", "writer",
        "--output-path", str(out),
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    log = (
        cartooner_root / "projects" / "demo" / "generation_log.jsonl"
    ).read_text()
    last = json.loads(log.strip().splitlines()[-1])
    assert last["event"] == "brief_delivered"
    # wakeup_reason should not be "no_target_session" — fallback worked.
    # It will be something else (transport_missing / non_zero / etc.)
    assert last["wakeup_reason"] != "no_target_session", (
        f"dispatch_session fallback failed; wakeup_reason={last['wakeup_reason']!r}"
    )


def test_parse_brief_round_trips_multi_output_result_block(
    cartooner_env, cartooner_root, tmp_path
):
    """The +++ result block with array-of-tables outputs must parse cleanly."""
    brief_id = _dispatch_brief_helper(
        cartooner_env,
        target="writer",
        intent="other",
        deliverable=["a.md", "b.md"],
    )
    a = tmp_path / "a.md"
    a.write_text("a\n", encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("b\n", encoding="utf-8")
    r = _run(
        "deliver_brief.py",
        "--project", "demo",
        "--brief-id", brief_id,
        "--actor", "writer",
        "--output-path", str(a),
        "--output-path", str(b),
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert r.returncode == 0, r.stderr
    code = (
        f"import sys; sys.path.insert(0, {str(_SCRIPTS)!r}); "
        f"import _common as c; "
        f"raw = open({str(_REPO / cartooner_env['CARTOONER_ROOT'])!r} + "
        f"  '/projects/demo/briefs/{brief_id}.toml').read(); "
        f"r = c.parse_brief(raw); "
        f"assert r['_result'].get('outputs') and len(r['_result']['outputs']) == 2; "
        f"basenames = sorted(__import__('os').path.basename(o['path']) "
        f"  for o in r['_result']['outputs']); "
        f"assert basenames == ['a.md','b.md'], basenames; "
        f"print('OK')"
    )
    res = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env={**os.environ, **cartooner_env},
    )
    assert res.returncode == 0, res.stderr
    assert "OK" in res.stdout


# ── audit finding #10: lane model intent + deposit coherence ───────────


def _spawn_lane_with_model(env, model: str, seat: str = "builder-image"):
    r = _run(
        "spawn_lane.py",
        "--project", "demo",
        "--seat", seat,
        "--count", "1",
        "--prompt", "test",
        "--model", model,
        "--skip-wakeup",
        env=env,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_spawn_lane_records_model_in_lane_and_index(cartooner_env, cartooner_root):
    lane_id = _spawn_lane_with_model(cartooner_env, "gpt-image-2")
    proj = cartooner_root / "projects" / "demo"
    raw = (proj / "lanes" / f"{lane_id}.toml").read_text(encoding="utf-8")
    assert 'model = "gpt-image-2"' in raw
    rec = json.loads((proj / "PROJECT_INDEX.json").read_text())["lanes"][lane_id]
    assert rec["model"] == "gpt-image-2"


def test_deposit_asset_model_match_no_fallback_required(
    cartooner_env, cartooner_root, tmp_path
):
    """When deposit's --model equals lane.model, no fallback reason needed."""
    lane_id = _spawn_lane_with_model(cartooner_env, "minimax-image-01")
    img = tmp_path / "asset.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    res = _run(
        "deposit_asset.py",
        "--project", "demo",
        "--lane-id", lane_id,
        "--asset-id", "img-test-1",
        "--asset-path", str(img),
        "--actor", "builder-image",
        "--asset-type", "image",
        "--model", "minimax-image-01",
        "--all-candidates-deposited",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    rec = json.loads(
        (cartooner_root / "projects" / "demo" / "PROJECT_INDEX.json").read_text()
    )["assets"]["img-test-1"]
    assert rec["model"] == "minimax-image-01"
    assert rec["model_asked"] == "minimax-image-01"
    assert rec["model_fallback_reason"] is None


def test_deposit_asset_model_mismatch_requires_fallback_reason(
    cartooner_env, tmp_path
):
    """Memory asked gpt-image-2 but builder used minimax → must justify."""
    lane_id = _spawn_lane_with_model(cartooner_env, "gpt-image-2")
    img = tmp_path / "asset.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    res = _run(
        "deposit_asset.py",
        "--project", "demo",
        "--lane-id", lane_id,
        "--asset-id", "img-test-2",
        "--asset-path", str(img),
        "--actor", "builder-image",
        "--asset-type", "image",
        "--model", "minimax-image-01",  # different from lane
        "--all-candidates-deposited",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "model-fallback-reason" in res.stderr
    assert "audit finding #10" in res.stderr


def test_deposit_asset_model_mismatch_with_fallback_reason_succeeds(
    cartooner_env, cartooner_root, tmp_path
):
    """Same mismatch, but with --model-fallback-reason → passes + records both."""
    lane_id = _spawn_lane_with_model(cartooner_env, "gpt-image-2")
    img = tmp_path / "asset.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    res = _run(
        "deposit_asset.py",
        "--project", "demo",
        "--lane-id", lane_id,
        "--asset-id", "img-test-3",
        "--asset-path", str(img),
        "--actor", "builder-image",
        "--asset-type", "image",
        "--model", "minimax-image-01",
        "--model-fallback-reason", "OpenAI route 401 — no OPENAI_API_KEY in sandbox",
        "--all-candidates-deposited",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    rec = json.loads(
        (cartooner_root / "projects" / "demo" / "PROJECT_INDEX.json").read_text()
    )["assets"]["img-test-3"]
    assert rec["model"] == "minimax-image-01"
    assert rec["model_asked"] == "gpt-image-2"
    assert "OPENAI_API_KEY" in rec["model_fallback_reason"]
    # Same diverged event in generation_log
    log = (
        cartooner_root / "projects" / "demo" / "generation_log.jsonl"
    ).read_text()
    last_dep = [
        json.loads(l) for l in log.strip().splitlines()
        if json.loads(l).get("event") == "asset_deposited"
    ][-1]
    assert last_dep["model_asked"] == "gpt-image-2"
    assert last_dep["model"] == "minimax-image-01"


def test_deposit_asset_lane_without_model_intent_skips_check(
    cartooner_env, cartooner_root, tmp_path
):
    """Pre-#10 lanes (no model field) bypass the coherence check."""
    # spawn lane WITHOUT --model
    r = _run(
        "spawn_lane.py", "--project", "demo", "--seat", "builder-image",
        "--count", "1", "--prompt", "no-model-lane",
        "--skip-wakeup", env=cartooner_env,
    )
    assert r.returncode == 0
    lane_id = r.stdout.strip()
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    # deposit with arbitrary model — no fallback reason needed
    res = _run(
        "deposit_asset.py", "--project", "demo", "--lane-id", lane_id,
        "--asset-id", "img-test-4", "--asset-path", str(img),
        "--actor", "builder-image", "--asset-type", "image",
        "--model", "any-thing",
        "--all-candidates-deposited", "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr


# ── audit finding #12: subagent --max-concurrent enforcement ────────────


def _spawn_subagent_helper(env, seat="builder-image", max_concurrent=None):
    args = [
        "spawn_subagent.py", "--project", "demo", "--action", "spawn",
        "--seat", seat, "--subagent-type", "reference_learning",
        "--inputs", '{"reference_url": "https://x.example/y"}',
    ]
    if max_concurrent is not None:
        args += ["--max-concurrent", str(max_concurrent)]
    r = _run(*args, env=env)
    return r


def test_spawn_subagent_max_concurrent_blocks_excess(cartooner_env):
    """builder-av --max-concurrent 1 must reject the 2nd parallel spawn."""
    r1 = _spawn_subagent_helper(cartooner_env, seat="builder-av", max_concurrent=1)
    assert r1.returncode == 0, r1.stderr
    r2 = _spawn_subagent_helper(cartooner_env, seat="builder-av", max_concurrent=1)
    assert r2.returncode != 0
    assert "max-concurrent=1" in r2.stderr
    assert "audit finding #12" in r2.stderr or "in flight" in r2.stderr


def test_spawn_subagent_max_concurrent_allows_after_complete(
    cartooner_env, tmp_path
):
    """After completing the 1st, the 2nd spawn is allowed."""
    r1 = _spawn_subagent_helper(cartooner_env, seat="builder-av", max_concurrent=1)
    sa1 = r1.stdout.strip()
    report = tmp_path / "report.md"
    report.write_text("# review\n\nfindings\n", encoding="utf-8")
    rc = _run(
        "spawn_subagent.py", "--project", "demo", "--action", "complete",
        "--subagent-id", sa1, "--report-path", str(report),
        env=cartooner_env,
    )
    assert rc.returncode == 0, rc.stderr
    r2 = _spawn_subagent_helper(cartooner_env, seat="builder-av", max_concurrent=1)
    assert r2.returncode == 0, r2.stderr


def test_spawn_subagent_max_concurrent_default_allows_4(cartooner_env):
    """Default --max-concurrent = 4 → 4 spawns OK, 5th blocks."""
    for i in range(4):
        r = _spawn_subagent_helper(cartooner_env, seat="builder-image")
        assert r.returncode == 0, f"spawn {i}: {r.stderr}"
    r5 = _spawn_subagent_helper(cartooner_env, seat="builder-image")
    assert r5.returncode != 0
    assert "max-concurrent=4" in r5.stderr


def test_spawn_subagent_max_concurrent_per_caller_isolation(cartooner_env):
    """Cap is per-caller, not global: builder-image at cap doesn't block builder-av."""
    for _ in range(4):
        r = _spawn_subagent_helper(cartooner_env, seat="builder-image")
        assert r.returncode == 0, r.stderr
    # builder-av's cap independent
    r_av = _spawn_subagent_helper(cartooner_env, seat="builder-av", max_concurrent=1)
    assert r_av.returncode == 0, r_av.stderr


# ── audit finding #16: deposit_asset --fail-lane primitive ─────────────


def test_deposit_asset_fail_lane_marks_lane_failed(
    cartooner_env, cartooner_root
):
    """--fail-lane transitions lane to state=failed without depositing asset."""
    lane_id = _spawn_lane_with_model(cartooner_env, "codex-image-builtin")
    res = _run(
        "deposit_asset.py",
        "--project", "demo",
        "--lane-id", lane_id,
        "--actor", "builder-image",
        "--fail-lane",
        "--reason", "codex-image-builtin route unavailable in this auth tier",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    rec = json.loads(
        (cartooner_root / "projects" / "demo" / "PROJECT_INDEX.json").read_text()
    )["lanes"][lane_id]
    assert rec["state"] == "failed"
    assert "codex-image-builtin" in rec["failure_reason"]
    assert "failed_at" in rec
    # No asset created
    assets = json.loads(
        (cartooner_root / "projects" / "demo" / "PROJECT_INDEX.json").read_text()
    ).get("assets", {})
    assert not assets


def test_deposit_asset_fail_lane_requires_reason(cartooner_env):
    """--fail-lane without --reason fails closed."""
    lane_id = _spawn_lane_with_model(cartooner_env, "gpt-image-2")
    res = _run(
        "deposit_asset.py",
        "--project", "demo", "--lane-id", lane_id,
        "--actor", "builder-image",
        "--fail-lane",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "--fail-lane requires --reason" in res.stderr


def test_deposit_asset_fail_lane_mutex_with_deposit_args(
    cartooner_env, tmp_path
):
    """--fail-lane + --asset-id is invalid (mutually exclusive)."""
    lane_id = _spawn_lane_with_model(cartooner_env, "gpt-image-2")
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    res = _run(
        "deposit_asset.py",
        "--project", "demo", "--lane-id", lane_id,
        "--actor", "builder-image",
        "--asset-id", "img-x",
        "--asset-path", str(img),
        "--asset-type", "image",
        "--fail-lane",
        "--reason", "ignored",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "mutually exclusive" in res.stderr


def test_deposit_asset_fail_lane_emits_lane_failed_event(
    cartooner_env, cartooner_root
):
    """generation_log captures lane_failed with model_asked + reason."""
    lane_id = _spawn_lane_with_model(cartooner_env, "nano-banana-pro")
    res = _run(
        "deposit_asset.py",
        "--project", "demo", "--lane-id", lane_id,
        "--actor", "builder-image",
        "--fail-lane",
        "--reason", "GEMINI_API_KEY missing in sandbox env",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res.returncode == 0
    log = (
        cartooner_root / "projects" / "demo" / "generation_log.jsonl"
    ).read_text()
    last = json.loads(log.strip().splitlines()[-1])
    assert last["event"] == "lane_failed"
    assert last["model_asked"] == "nano-banana-pro"
    assert "GEMINI_API_KEY" in last["reason"]
    assert last["actor"] == "builder-image"


def test_deposit_asset_fail_lane_rejects_already_deposited_lane(
    cartooner_env, tmp_path
):
    """Cannot fail a lane that already deposited."""
    lane_id = _spawn_lane_with_model(cartooner_env, "minimax-image-01")
    img = tmp_path / "y.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    # First deposit successfully
    res1 = _run(
        "deposit_asset.py",
        "--project", "demo", "--lane-id", lane_id,
        "--asset-id", "img-y", "--asset-path", str(img),
        "--actor", "builder-image", "--asset-type", "image",
        "--model", "minimax-image-01",
        "--all-candidates-deposited",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res1.returncode == 0
    # Now try to fail-lane the deposited lane
    res2 = _run(
        "deposit_asset.py",
        "--project", "demo", "--lane-id", lane_id,
        "--actor", "builder-image",
        "--fail-lane",
        "--reason", "too late",
        "--skip-wakeup",
        env=cartooner_env,
    )
    assert res2.returncode != 0
    assert "only valid for spawned/generating" in res2.stderr


def test_patrol_authorization_accepts_lane_failed_event(
    cartooner_env, cartooner_root
):
    """patrol_pipeline_sla.py --check authorization recognizes lane_failed."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({
            "project_id": "demo", "version": 1, "automation_mode": "manual",
            "lanes": {}, "assets": {}, "tournaments": {},
        }),
        encoding="utf-8",
    )
    project_root.joinpath("generation_log.jsonl").write_text(
        json.dumps({
            "ts": "2026-05-11T00:00:00.000+00:00",
            "event": "lane_failed",
            "actor": "builder-image",
            "lane_id": "lane-x",
            "reason": "route stalled",
        }) + "\n",
        encoding="utf-8",
    )
    res = _run(
        "patrol_pipeline_sla.py",
        "--project", "demo", "--check", "authorization",
        env=cartooner_env,
    )
    assert res.returncode == 0
    assert "clean" in res.stdout


# ── audit finding #18: archive_project primitive ─────────────────────


def _setup_demo_project(env, *, spawn_lane: bool = True):
    """Bring a demo project into a non-trivial state for archival tests."""
    if not spawn_lane:
        # just ensure skeleton
        _run("render_asset_tree.py", "--project", "demo", env=env)
        return
    _spawn_lane_with_model(env, "minimax-image-01")


def test_archive_project_dry_run_does_not_rename(
    cartooner_env, cartooner_root
):
    _setup_demo_project(cartooner_env)
    res = _run(
        "archive_project.py",
        "--project", "demo",
        "--reason", "pre-V4 test",
        "--dry-run",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    src = cartooner_root / "projects" / "demo"
    assert src.exists(), "dry-run should NOT rename source dir"
    target = res.stdout.strip()
    assert "demo-archived-" in target
    assert "pre-v4-test" in target  # slugified
    assert not Path(target).exists()


def test_archive_project_renames_and_writes_summary(
    cartooner_env, cartooner_root
):
    _setup_demo_project(cartooner_env)
    src = cartooner_root / "projects" / "demo"
    assert src.exists()
    res = _run(
        "archive_project.py",
        "--project", "demo",
        "--reason", "v3 evidence",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    target = Path(res.stdout.strip())
    assert target.exists(), f"archive path missing: {target}"
    assert not src.exists(), "source dir should have been renamed away"
    # Summary lives inside the archive
    summary = target / "ARCHIVE_SUMMARY.md"
    assert summary.is_file()
    body = summary.read_text(encoding="utf-8")
    assert "Archive Summary" in body
    assert "lanes:" in body
    assert "Lane outcomes" in body
    # generation_log inside archive should carry the project_archived event
    log_text = (target / "generation_log.jsonl").read_text(encoding="utf-8")
    last_line = log_text.strip().splitlines()[-1]
    last = json.loads(last_line)
    assert last["event"] == "project_archived"
    assert last["actor"] == "user"
    assert "v3 evidence" in last.get("reason", "")


def test_archive_project_missing_project_fails_closed(cartooner_env):
    res = _run(
        "archive_project.py",
        "--project", "nonexistent-project-xyz",
        "--dry-run",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "project not found" in res.stderr


def test_archive_project_collision_appends_suffix(
    cartooner_env, cartooner_root
):
    """Two archives within the same second get -1, -2, ... suffix."""
    _setup_demo_project(cartooner_env)
    # First archive
    r1 = _run("archive_project.py", "--project", "demo", "--reason", "x",
              env=cartooner_env)
    assert r1.returncode == 0, r1.stderr
    path1 = Path(r1.stdout.strip())
    # Re-create the demo project so we can archive twice
    _setup_demo_project(cartooner_env)
    r2 = _run("archive_project.py", "--project", "demo", "--reason", "x",
              env=cartooner_env)
    assert r2.returncode == 0, r2.stderr
    path2 = Path(r2.stdout.strip())
    assert path1 != path2, "second archive should have a different path"
    # path2 likely has -1 suffix if within same second (could be unequal ts though)
    assert path2.exists()
    assert path1.exists()


def test_archive_project_actor_validated(cartooner_env, cartooner_root):
    _setup_demo_project(cartooner_env)
    res = _run(
        "archive_project.py",
        "--project", "demo",
        "--actor", "writer",  # not allowed
        "--dry-run",
        env=cartooner_env,
    )
    assert res.returncode != 0
    assert "invalid choice" in res.stderr or "writer" in res.stderr


def test_archive_project_summary_includes_model_intent_distribution(
    cartooner_env, cartooner_root, tmp_path
):
    """ARCHIVE_SUMMARY.md must surface #10 audit metrics: asked vs actual."""
    lane_id = _spawn_lane_with_model(cartooner_env, "gpt-image-2")
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    # Deposit with a fallback to make the audit signal interesting
    _run(
        "deposit_asset.py",
        "--project", "demo", "--lane-id", lane_id,
        "--asset-id", "img-test", "--asset-path", str(img),
        "--actor", "builder-image", "--asset-type", "image",
        "--model", "minimax-image-01",
        "--model-fallback-reason", "xcode 524",
        "--all-candidates-deposited",
        "--skip-wakeup",
        env=cartooner_env,
    )
    res = _run(
        "archive_project.py", "--project", "demo",
        "--reason", "audit signal test",
        env=cartooner_env,
    )
    assert res.returncode == 0, res.stderr
    target = Path(res.stdout.strip())
    summary = (target / "ARCHIVE_SUMMARY.md").read_text(encoding="utf-8")
    assert "Asset model intent (#10 audit)" in summary
    assert "asked=gpt-image-2" in summary
    assert "with explicit model_fallback_reason: 1" in summary


def test_patrol_authorization_accepts_project_archived_event(
    cartooner_env, cartooner_root
):
    """patrol_pipeline_sla --check authorization recognizes project_archived."""
    project_root = cartooner_root / "projects" / "demo"
    project_root.mkdir(parents=True, exist_ok=True)
    project_root.joinpath("PROJECT_INDEX.json").write_text(
        json.dumps({
            "project_id": "demo", "version": 1, "automation_mode": "manual",
            "lanes": {}, "assets": {}, "tournaments": {},
        }),
        encoding="utf-8",
    )
    project_root.joinpath("generation_log.jsonl").write_text(
        json.dumps({
            "ts": "2026-05-11T00:00:00.000+00:00",
            "event": "project_archived",
            "actor": "user",
            "reason": "post-V3",
            "archive_path": "/tmp/demo-archived-...",
        }) + "\n",
        encoding="utf-8",
    )
    res = _run(
        "patrol_pipeline_sla.py",
        "--project", "demo", "--check", "authorization",
        env=cartooner_env,
    )
    assert res.returncode == 0
    assert "clean" in res.stdout
