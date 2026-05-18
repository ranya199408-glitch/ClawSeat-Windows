"""cartooner-harness shared state primitives.

Single shared module (not a package) intentionally — keep the protocol's
runtime small. All I/O is against ~/.cartooner/projects/<project_id>/.

Path resolution honors `CARTOONER_ROOT` env var (used by tests / sandbox);
default is `~/.cartooner`.

Schemas
-------

PROJECT_INDEX.json (top-level state):
  {
    "project_id": "<id>",
    "version": 1,
    "created_at": "<iso>",
    "automation_mode": "manual" | "auto",
    "lanes":       {<lane_id>: {state, seat, count, shot_id, triggered_by, created_at}},
    "assets":      {<asset_id>: {asset_id, path, type, lane, model, seed, ...}},
    "tournaments": {<round_id>: {candidates, picked, ...}}
  }

generation_log.jsonl (append-only event stream):
  {"ts": "<iso>", "event": "<name>", "actor": "<seat|user|patrol>", ...}

lanes/<lane_id>.toml (per-lane state):
  id / created_at / state / seat / count / prompt / shot_id / input_image /
  style_bible_ref / character_dna_ref / parent_lane / triggered_by /
  [result] candidates / deposited_at

`no-image-policy` is enforced at design time (no helper here reads asset
content); helpers only stat asset files for `file_size` metadata.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CARTOONER_ROOT_ENV = "CARTOONER_ROOT"

VALID_SEATS = ("memory", "writer", "builder-image", "builder-av", "patrol")
VALID_LANE_STATES = ("spawned", "generating", "deposited", "picked", "failed", "superseded")
VALID_ASSET_TYPES = ("image", "video", "audio", "text")


def cartooner_root() -> Path:
    override = os.environ.get(CARTOONER_ROOT_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cartooner"


def project_root(project_id: str) -> Path:
    return cartooner_root() / "projects" / project_id


def ensure_project_skeleton(project_id: str) -> Path:
    validate_id_token(project_id, kind="--project")
    root = project_root(project_id)
    for sub in (
        "lanes",
        "assets/images",
        "assets/videos",
        "assets/audios",
        "assets/texts",
        "briefs",
        "subagents",
        "tournaments",
        "iterations",
        "escalations",
        "references_learned",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def load_project_index(project_id: str) -> dict[str, Any]:
    validate_id_token(project_id, kind="--project")
    path = project_root(project_id) / "PROJECT_INDEX.json"
    if not path.exists():
        return {
            "project_id": project_id,
            "version": 1,
            "created_at": now_iso(),
            "automation_mode": "manual",
            "lanes": {},
            "assets": {},
            "tournaments": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def write_project_index(project_id: str, data: dict[str, Any]) -> None:
    ensure_project_skeleton(project_id)
    path = project_root(project_id) / "PROJECT_INDEX.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def update_project_index(project_id: str, mutator):
    """Atomic read-modify-write on PROJECT_INDEX.json under exclusive lock.

    Audit finding #3: spawn_lane / deposit_asset / pick_winner /
    iterate_prompt / etc. all do load_project_index → mutate → write.
    Without a lock, two concurrent calls (memory's parallel
    subprocess.run) could race: both load same baseline, each adds its
    own lane/asset, last writer wins → one record silently dropped from
    the index (lane file on disk is intact but orphaned).

    `mutator(index)` receives the freshly-loaded dict and may mutate
    in-place or return a new dict; the result is written under the lock.

    Lock file lives next to the index; flock is released by the kernel
    even if the process crashes, so no manual unlock-on-error needed.
    """
    ensure_project_skeleton(project_id)
    path = project_root(project_id) / "PROJECT_INDEX.json"
    lock_path = path.with_suffix(".json.lock")
    try:
        import fcntl
    except ImportError:  # pragma: no cover — non-POSIX (Windows)
        # Without flock we cannot guarantee atomicity; degrade to plain
        # read-modify-write and warn loudly. Producer should rerun on a
        # POSIX host for correctness-critical operations.
        index = load_project_index(project_id)
        result = mutator(index)
        index_to_write = result if result is not None else index
        write_project_index(project_id, index_to_write)
        return index_to_write

    with open(lock_path, "w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            index = load_project_index(project_id)
            result = mutator(index)
            index_to_write = result if result is not None else index
            write_project_index(project_id, index_to_write)
            return index_to_write
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def append_generation_log(project_id: str, event: dict[str, Any]) -> None:
    ensure_project_skeleton(project_id)
    path = project_root(project_id) / "generation_log.jsonl"
    payload = {"ts": now_iso(), **event}
    line = json.dumps(payload, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_lane(project_id: str, lane_id: str) -> dict[str, Any] | None:
    path = project_root(project_id) / "lanes" / f"{lane_id}.toml"
    if not path.exists():
        return None
    try:
        import tomllib  # py3.11+
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]
    with path.open("rb") as fh:
        return tomllib.load(fh)


def write_lane(project_id: str, lane_id: str, data: dict[str, Any]) -> None:
    ensure_project_skeleton(project_id)
    path = project_root(project_id) / "lanes" / f"{lane_id}.toml"
    path.write_text(serialize_toml(data), encoding="utf-8")


def load_brief(project_id: str, brief_id: str) -> dict[str, Any] | None:
    """Load a brief TOML file (frontmatter + body).

    Returns a dict with both the frontmatter fields and a `body` key
    holding the markdown body string. Returns None if the file is missing
    or malformed.
    """
    path = project_root(project_id) / "briefs" / f"{brief_id}.toml"
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    return parse_brief(raw)


def parse_brief(raw: str) -> dict[str, Any] | None:
    """Parse a brief frontmatter+body file into {**frontmatter, body: <md>}.

    Supports an optional appended `+++ result\\n<TOML>\\n+++` block written
    by `deliver_brief.py`; that block is stripped from the body and exposed
    on the returned dict as `_result` (parsed TOML or {} on parse error).
    """
    marker = "+++"
    if not raw.startswith(marker):
        return None
    end = raw.find("\n" + marker, len(marker))
    if end < 0:
        return None
    fm_text = raw[len(marker):end].strip()
    rest = raw[end + len("\n" + marker):]
    # Strip a trailing result block if present:
    #   <body>\n+++ result\n<resfm>\n+++\n
    body = rest
    result_payload: dict[str, Any] = {}
    res_marker = "\n+++ result\n"
    res_idx = rest.find(res_marker)
    if res_idx >= 0:
        body = rest[:res_idx]
        tail = rest[res_idx + len(res_marker):]
        end_res = tail.find("\n+++")
        if end_res >= 0:
            res_text = tail[:end_res].strip()
            try:
                import tomllib as _tl
            except ModuleNotFoundError:  # pragma: no cover
                import tomli as _tl  # type: ignore[no-redef]
            try:
                result_payload = _tl.loads(res_text)
            except Exception:
                result_payload = {}
    body = body.lstrip("\n").rstrip("\n")
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        fm = tomllib.loads(fm_text)
    except Exception:
        return None
    fm["body"] = body
    if result_payload:
        fm["_result"] = result_payload
    return fm


def write_brief(
    project_id: str,
    brief_id: str,
    frontmatter: dict[str, Any],
    body: str,
) -> None:
    """Write a brief TOML file with `+++` frontmatter markers + body."""
    ensure_project_skeleton(project_id)
    briefs_dir = project_root(project_id) / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    path = briefs_dir / f"{brief_id}.toml"
    fm_serialized = serialize_toml(frontmatter).rstrip("\n")
    parts = ["+++", fm_serialized, "+++", "", body.rstrip("\n"), ""]
    path.write_text("\n".join(parts), encoding="utf-8")


def resolve_seat_session(project_id: str, seat_id: str) -> str | None:
    """Look up a seat's canonical tmux session name.

    Used by dispatch_brief / spawn_lane / deposit_asset wakeup paths.
    Returns None when no session record exists (e.g., tests with mocked
    HOME) — callers treat that as "skip wakeup, just write durable file".

    Resolution order for the agents root:
      1. $CLAWSEAT_AGENTS_ROOT (explicit override; tests / future per-host)
      2. $AGENTS_ROOT (set by core/launchers/agent-launcher.sh inside seat
         sandbox HOME — points at the operator's REAL_HOME/.agents)
      3. $CLAWSEAT_REAL_HOME / .agents (legacy override)
      4. $AGENT_HOME / .agents (also set by agent-launcher)
      5. ~/.agents (last-resort; only correct when running from the
         operator's real shell, not from inside a seat sandbox)
    """
    candidates: list[Path] = []
    explicit = os.environ.get("CLAWSEAT_AGENTS_ROOT", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    agents_root = os.environ.get("AGENTS_ROOT", "").strip()
    if agents_root:
        candidates.append(Path(agents_root).expanduser())
    real_home = os.environ.get("CLAWSEAT_REAL_HOME", "").strip()
    if real_home:
        candidates.append(Path(real_home).expanduser() / ".agents")
    agent_home = os.environ.get("AGENT_HOME", "").strip()
    if agent_home:
        candidates.append(Path(agent_home).expanduser() / ".agents")
    candidates.append(Path(os.path.expanduser("~")) / ".agents")

    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]
    seen: set[str] = set()
    for root in candidates:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        path = root / "sessions" / project_id / seat_id / "session.toml"
        if not path.exists():
            continue
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        except Exception:
            continue
        session = data.get("session")
        if session:
            return str(session)
    return None


def resolve_wakeup_target(args, brief: dict | None = None, fallback_seat: str = "memory") -> str:
    """Resolve wakeup tmux session: explicit arg > brief.dispatch_session > resolve_seat_session(fallback_seat).

    Centralises the 3-layer fallback so all callers stay in sync (audit §10.6).

    Layer 1 — args.target_session (explicit operator override).
    Layer 2 — brief frontmatter dispatch_session (captured at dispatch time;
               lets cross-project wakeups find the right memory session even
               when resolve_seat_session would return nothing; audit finding #9).
    Layer 3 — resolve_seat_session(project_id, fallback_seat) (project-bound
               default; seat name varies per caller: "memory" for deposit/deliver,
               args.target for dispatch_brief, args.seat for spawn_lane).
    """
    explicit = (getattr(args, "target_session", "") or "").strip()
    if explicit:
        return explicit
    if brief is not None:
        from_brief = (brief.get("dispatch_session") or "").strip()
        if from_brief:
            return from_brief
    project_id = getattr(args, "project", None)
    if project_id:
        fallback = resolve_seat_session(project_id, fallback_seat) or ""
        if fallback:
            return fallback
    return ""


def send_wakeup(
    project_id: str,
    target_session: str,
    message: str,
    *,
    skip: bool = False,
) -> dict[str, Any]:
    """Best-effort tmux wakeup via core/shell-scripts/send-and-verify.sh.

    Returns a dict {ok: bool, reason: str|None, exit_code: int|None}.
    Never raises; never blocks the caller's audit write. When skip=True
    or send-and-verify is missing or returns non-zero, the durable brief /
    lane is still considered authoritative — wakeup is the signal, not
    the truth.
    """
    if skip:
        return {"ok": False, "reason": "skipped_by_caller", "exit_code": None}
    if not target_session:
        return {"ok": False, "reason": "no_target_session", "exit_code": None}
    transport = _send_and_verify_path()
    if transport is None or not transport.exists():
        return {"ok": False, "reason": "transport_missing", "exit_code": None}
    import subprocess
    try:
        result = subprocess.run(
            [
                "bash",
                str(transport),
                "--project",
                project_id,
                target_session,
                message,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "reason": f"exception:{exc}", "exit_code": None}
    if result.returncode == 0:
        return {"ok": True, "reason": None, "exit_code": 0}
    return {
        "ok": False,
        "reason": (result.stderr or result.stdout or "non_zero_exit").strip()[:240],
        "exit_code": result.returncode,
    }


def _send_and_verify_path() -> Path | None:
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        candidate = parent / "core" / "shell-scripts" / "send-and-verify.sh"
        if candidate.exists():
            return candidate
    return None


def detect_tmux_session() -> str | None:
    """Autodetect the current tmux session name (best-effort).

    Used by dispatch_brief.py so the dispatching seat doesn't have to
    remember its own tmux session — we capture it for the wakeup return
    path (deliver_brief uses it as the default --target-session).

    Returns the session name string, or None if we are not in tmux or
    the lookup fails. Never raises.
    """
    if not os.environ.get("TMUX"):
        return None
    import subprocess
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    name = (result.stdout or "").strip()
    return name or None


def serialize_toml(data: dict[str, Any]) -> str:
    """Minimal TOML serializer for our flat-with-one-section lane schema.

    Supports str / int / float / bool / list[str] / list[dict] (array-of-tables) /
    nested table (one level). Skips keys whose value is None (to keep TOML
    clean).
    """
    top: list[str] = []
    sections: list[str] = []
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict):
            sections.append(f"\n[{key}]")
            for sub_key, sub_value in value.items():
                if sub_value is None:
                    continue
                sections.append(_kv_line(sub_key, sub_value))
            continue
        # list[dict] → TOML array-of-tables; lets us emit
        # `outputs = [{path,...}, ...]` as repeated [[outputs]] sections
        # for human readability while round-tripping cleanly through tomllib.
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            for entry in value:
                sections.append(f"\n[[{key}]]")
                for sub_key, sub_value in entry.items():
                    if sub_value is None:
                        continue
                    sections.append(_kv_line(sub_key, sub_value))
            continue
        top.append(_kv_line(key, value))
    return "\n".join(top + sections) + "\n"


def _kv_line(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return f"{key} = {'true' if value else 'false'}"
    if isinstance(value, (int, float)):
        return f"{key} = {value}"
    if isinstance(value, str):
        if "\n" in value:
            # Use TOML multiline basic string for values containing newlines
            safe = value.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
            return f'{key} = """\n{safe}\n"""'
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'{key} = "{escaped}"'
    if isinstance(value, list):
        if not value:
            return f"{key} = []"
        items = []
        for item in value:
            if isinstance(item, str):
                esc = item.replace("\\", "\\\\").replace('"', '\\"')
                items.append(f'"{esc}"')
            elif isinstance(item, bool):
                items.append("true" if item else "false")
            else:
                items.append(str(item))
        return f"{key} = [{', '.join(items)}]"
    return f'{key} = "{value}"'


def fail_closed(message: str, code: int = 1) -> None:
    """Print to stderr and exit non-zero. Strict fail-closed semantics."""
    print(f"[cartooner-harness] FAIL: {message}", file=sys.stderr)
    sys.exit(code)


def validate_id_token(token: str, *, kind: str) -> str:
    """Reject path-like / control-char ids early.

    Defense-in-depth for any user-controlled id that lands in a file
    path (round_id, lane_id, brief_id, subagent_id, asset_id, etc.).
    Without this, a malicious or malformed id like `../../../tmp/evil`
    or `\\x00` would let `tournaments/<id>.toml` write outside the
    project root or trip filesystem APIs.

    Allowed: alphanumerics, dash, underscore, dot — but dot may NOT
    appear at the start (no `.hidden`) and `..` is rejected outright.
    Length capped at 128 bytes.
    """
    if not token or not str(token).strip():
        fail_closed(f"{kind} must be a non-empty token")
    if len(token) > 128:
        fail_closed(f"{kind} {token[:32]!r}... exceeds 128 bytes")
    bad_chars = ("/", "\\", "~", "$", "\n", "\r", "\t", "\0", " ", ":")
    for ch in bad_chars:
        if ch in token:
            fail_closed(
                f"{kind} must not contain path / control chars; got {token!r}"
            )
    if ".." in token:
        fail_closed(f"{kind} must not contain '..'; got {token!r}")
    if token.startswith(".") or token.startswith("-"):
        fail_closed(f"{kind} must not start with '.' or '-'; got {token!r}")
    return token
