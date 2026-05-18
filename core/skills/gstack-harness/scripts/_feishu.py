"""Feishu / Lark messaging helpers — extracted from _common.py."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from _utils import (
    AGENT_HOME,
    OPENCLAW_AGENTS_ROOT,
    OPENCLAW_CONFIG_PATH,
    OPENCLAW_FEISHU_SEND_SH,
    OPENCLAW_HOME,
    load_json,
    load_toml,
    run_command_with_env,
)


# ── Real-user-home resolution ─────────────────────────────────────────
#
# Seats run inside a sandbox HOME at
#   ~/.agents/runtime/identities/<tool>/<auth>/<identity>/home/
# so Path.home() inside a seat returns THAT, not the operator's real HOME.
# Many resources live at the operator's real HOME — lark-cli config,
# OpenClaw workspace-koder WORKSPACE_CONTRACT.toml with the per-project
# feishu_group_id, the OpenClaw openclaw.json — and if we resolve them
# against the sandbox HOME they all miss and we silently fall off canonical
# paths. That is EXACTLY what caused planner→koder `complete_handoff.py`
# to route through tmux (because resolve_primary_feishu_group_id returned
# None under sandbox HOME) and hard-fail when koder's phantom tmux
# session was missing.
#
# Canonical implementation lives in core/lib/real_home.py; this module
# adds a feishu-specific LARK_CLI_HOME pre-check and then delegates.

import sys as _sys
from pathlib import Path as _Path

_CORE_LIB = str(_Path(__file__).resolve().parents[3] / "lib")
if _CORE_LIB not in _sys.path:
    _sys.path.insert(0, _CORE_LIB)
from real_home import (  # noqa: E402
    is_sandbox_home as _is_sandbox_home,
    real_user_home as _canonical_real_user_home,
)


def _real_user_home() -> Path:
    """Feishu-aware wrapper: honor LARK_CLI_HOME then delegate to canonical.

    LARK_CLI_HOME is a feishu-specific override that the installer uses to
    point lark-cli at a test HOME; we respect it before the generic probe.
    """
    override = os.environ.get("LARK_CLI_HOME")
    if override:
        return Path(override).expanduser()
    return _canonical_real_user_home()


def _resolve_effective_home() -> Path:
    """Return effective HOME: respects CLAWSEAT_SANDBOX_HOME_STRICT=1 for tests."""
    if os.environ.get("CLAWSEAT_SANDBOX_HOME_STRICT") == "1":
        return Path.home()
    return _real_user_home()


# ── Delegation report constants ──────────────────────────────────────

DELEGATION_REPORT_HEADER = "OC_DELEGATION_REPORT_V1"
VALID_DELEGATION_LANES = {
    "planning", "builder", "reviewer", "patrol", "designer", "frontstage",
}
VALID_DELEGATION_REPORT_STATUSES = {
    "in_progress", "done", "needs_decision", "blocked",
}
VALID_DELEGATION_DECISION_HINTS = {
    "hold", "proceed", "ask_user", "retry", "escalate", "close",
}
VALID_DELEGATION_USER_GATES = {"none", "optional", "required"}
VALID_DELEGATION_NEXT_ACTIONS = {
    "wait", "consume_closeout", "ask_user",
    "retry_current_lane", "surface_blocker", "finalize_chain",
}


# ── Group ID resolution ──────────────────────────────────────────────

# Canonical Feishu open-chat id prefix. Every resolved group we actually
# pass to `lark-cli` must match this — other strings (e.g. display names,
# account ids, stray `"*"` wildcards, typo'd prefixes) are filtered out
# early with a one-line stderr warning so the operator sees the typo
# instead of getting a cryptic 404 from the downstream lark-cli call.
# Audit M5.
_FEISHU_GROUP_ID_RE = re.compile(r"^oc_[A-Za-z0-9_-]+$")


def is_valid_feishu_group_id(value: str) -> bool:
    """True when *value* has the canonical `oc_<10+ alphanum>` shape."""
    if not value:
        return False
    return bool(_FEISHU_GROUP_ID_RE.match(value))


def _reject_invalid_feishu_group_id(candidate: str, *, source: str) -> bool:
    """If *candidate* fails the canonical shape check, emit a one-line
    stderr warning referencing *source* and return False. Returns True
    when the id is well-formed. Keeps failure visible without aborting
    the wider resolve path — other sources may still yield a valid id.
    """
    if is_valid_feishu_group_id(candidate):
        return True
    import sys as _sys
    print(
        f"warn: Feishu group id {candidate!r} from {source} does not match "
        "canonical 'oc_<alphanum>' shape; discarded (audit M5).",
        file=_sys.stderr,
    )
    return False


def collect_feishu_group_keys(payload: Any, *, found: list[str]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and key.startswith("group:"):
                group_id = key.split("group:", 1)[1].strip()
                if (
                    group_id
                    and group_id not in found
                    and _reject_invalid_feishu_group_id(group_id, source="sessions.json group: key")
                ):
                    found.append(group_id)
            collect_feishu_group_keys(value, found=found)
    elif isinstance(payload, list):
        for item in payload:
            collect_feishu_group_keys(item, found=found)


def collect_feishu_group_ids_from_config(config: dict[str, Any]) -> list[str]:
    found: list[str] = []

    def add_group_id(value: Any) -> None:
        group_id = str(value).strip()
        if (
            group_id
            and group_id != "*"
            and group_id not in found
            and _reject_invalid_feishu_group_id(group_id, source="openclaw.json")
        ):
            found.append(group_id)

    channels = config.get("channels")
    if isinstance(channels, dict):
        feishu = channels.get("feishu")
        if isinstance(feishu, dict):
            groups = feishu.get("groups")
            if isinstance(groups, dict):
                for group_id in groups.keys():
                    add_group_id(group_id)
            accounts = feishu.get("accounts")
            if isinstance(accounts, dict):
                default_account = feishu.get("defaultAccount")
                if isinstance(default_account, str):
                    default_account_payload = accounts.get(default_account)
                    if isinstance(default_account_payload, dict):
                        default_groups = default_account_payload.get("groups")
                        if isinstance(default_groups, dict):
                            for group_id in default_groups.keys():
                                add_group_id(group_id)
                for account_payload in accounts.values():
                    if not isinstance(account_payload, dict):
                        continue
                    account_groups = account_payload.get("groups")
                    if isinstance(account_groups, dict):
                        for group_id in account_groups.keys():
                            add_group_id(group_id)
    return found


def collect_feishu_group_ids_from_sessions() -> list[str]:
    found: list[str] = []
    if not OPENCLAW_AGENTS_ROOT.exists():
        return found
    for path in sorted(OPENCLAW_AGENTS_ROOT.glob("*/sessions/sessions.json")):
        try:
            payload = load_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        if payload is None:
            continue
        collect_feishu_group_keys(payload, found=found)
    return found


def _resolve_project_heartbeat_owner(project: str) -> str:
    profile_path = _real_user_home() / ".agents" / "profiles" / f"{project}-profile-dynamic.toml"
    if profile_path.exists():
        profile = load_toml(profile_path) or {}
        resolved = str(profile.get("heartbeat_owner", "")).strip()
        if resolved:
            return resolved
    return "koder"


def _project_contract_paths(project: str) -> list[Path]:
    real_home = _real_user_home()
    heartbeat_owner = _resolve_project_heartbeat_owner(project)
    candidates: list[Path] = [
        real_home / ".agents" / "workspaces" / project / heartbeat_owner / "WORKSPACE_CONTRACT.toml",
    ]
    for contract_path in sorted((real_home / ".openclaw").glob("workspace-*/WORKSPACE_CONTRACT.toml")):
        contract = load_toml(contract_path) or {}
        project_field = str(contract.get("project", "")).strip()
        if project_field and project_field != project:
            continue
        seat_id = str(contract.get("seat_id", "")).strip()
        if seat_id and seat_id != heartbeat_owner:
            continue
        candidates.append(contract_path)
    return candidates


def _project_binding_path(project: str) -> Path:
    """Location of the per-project Feishu binding SSOT (C2).

    `~/.agents/tasks/<project>/PROJECT_BINDING.toml` holds:
        project = "<name>"
        feishu_group_id = "oc_..."
        feishu_bot_account = "koder"
        bound_at = "<ISO8601>"

    When the file exists, it ranks BELOW the env override and ABOVE the
    legacy WORKSPACE_CONTRACT.toml field.
    """
    return _real_user_home() / ".agents" / "tasks" / project / "PROJECT_BINDING.toml"


# ── Strict resolver (C1): never guess, never silently fall back ──────


class FeishuGroupResolutionError(RuntimeError):
    """Raised when the per-project Feishu group cannot be resolved strictly.

    C1 guardrail: in multi-project mode the single biggest danger is *not*
    "failed to send" but "guessed the wrong group and sent successfully".
    Callers that need a group MUST either pass one explicitly or get a
    hard failure here — never a silent fallback to the first group in
    openclaw.json or the first seen group in sessions.json.
    """

    def __init__(
        self,
        reason: str,
        *,
        project: str | None = None,
        attempted_sources: list[str] | None = None,
    ) -> None:
        self.reason = reason
        self.project = project
        self.attempted_sources = list(attempted_sources or [])
        super().__init__(reason)


def _env_override_group_id() -> tuple[str, str] | None:
    """Return (group_id, source) for a well-formed env override, else None."""
    for env_name in ("CLAWSEAT_FEISHU_GROUP_ID", "OPENCLAW_FEISHU_GROUP_ID"):
        raw = os.environ.get(env_name)
        if not raw:
            continue
        resolved = raw.strip()
        if not resolved:
            continue
        if _reject_invalid_feishu_group_id(resolved, source=f"{env_name} env var"):
            return resolved, f"env:{env_name}"
    return None


def resolve_feishu_group_strict(project: str) -> tuple[str, str]:
    """Strictly resolve ``project`` → ``(group_id, source)``.

    Priority (no fallbacks beyond these):
      1. Env override: CLAWSEAT_FEISHU_GROUP_ID / OPENCLAW_FEISHU_GROUP_ID
      2. ``~/.agents/tasks/<project>/PROJECT_BINDING.toml`` (C2 SSOT)
      3. Project WORKSPACE_CONTRACT.toml ``feishu_group_id`` field

    Raises :class:`FeishuGroupResolutionError` when ``project`` is falsy
    or when no project-scoped source yields a valid group id. This is the
    P0 contract: **no global openclaw.json[0] / sessions.json[0] fallback**.
    """
    attempted: list[str] = []

    if not project or not str(project).strip():
        raise FeishuGroupResolutionError(
            "project is required for Feishu group resolution",
            project=project,
            attempted_sources=attempted,
        )
    project = project.strip()

    env_hit = _env_override_group_id()
    attempted.append("env:CLAWSEAT_FEISHU_GROUP_ID|OPENCLAW_FEISHU_GROUP_ID")
    if env_hit is not None:
        return env_hit

    binding_path = _project_binding_path(project)
    attempted.append(f"project_binding:{binding_path}")
    if binding_path.exists():
        binding = load_toml(binding_path) or {}
        binding_project = str(binding.get("project", "")).strip()
        if binding_project and binding_project != project:
            # Mismatched binding file — refuse rather than pick something.
            raise FeishuGroupResolutionError(
                f"PROJECT_BINDING.toml at {binding_path} declares project="
                f"{binding_project!r} but caller requested {project!r}",
                project=project,
                attempted_sources=attempted,
            )
        gid = str(binding.get("feishu_group_id", "")).strip()
        if gid and _reject_invalid_feishu_group_id(
            gid, source=f"PROJECT_BINDING.toml at {binding_path}"
        ):
            return gid, f"project_binding:{binding_path}"

    for cp in _project_contract_paths(project):
        attempted.append(f"workspace_contract:{cp}")
        if cp.exists():
            contract = load_toml(cp) or {}
            gid = str(contract.get("feishu_group_id", "")).strip()
            if gid and _reject_invalid_feishu_group_id(
                gid, source=f"WORKSPACE_CONTRACT.toml at {cp}"
            ):
                return gid, f"workspace_contract:{cp}"

    raise FeishuGroupResolutionError(
        f"no feishu_group_id binding for project={project!r}; "
        "set CLAWSEAT_FEISHU_GROUP_ID, create "
        f"{_project_binding_path(project)}, or add feishu_group_id to "
        "the project's WORKSPACE_CONTRACT.toml. "
        "No global openclaw.json / sessions.json fallback is consulted "
        "(C1 guardrail: refuse to guess).",
        project=project,
        attempted_sources=attempted,
    )


def resolve_primary_feishu_group_id(project: str | None = None) -> str | None:
    """Backwards-compatible resolver returning ``None`` on failure.

    Kept so existing call-sites and tests that expected ``None`` for
    "unresolved" keep working. Internally delegates to
    :func:`resolve_feishu_group_strict` and swallows
    :class:`FeishuGroupResolutionError`.

    **Crucially, this function no longer falls back to openclaw.json's
    first group or sessions.json's first group** — those paths were the
    source of cross-project group confusion (C1 guardrail).
    """
    if project is None or not str(project).strip():
        # Warn loudly: callers that hit this path would previously have
        # picked the first group out of global config — a silent guess.
        env_hit = _env_override_group_id()
        if env_hit is not None:
            return env_hit[0]
        import sys as _sys
        print(
            "warn: resolve_primary_feishu_group_id called without a project "
            "argument; returning None instead of guessing from openclaw.json "
            "(C1 guardrail). Pass project=... or use resolve_feishu_group_strict().",
            file=_sys.stderr,
        )
        return None
    try:
        group_id, _source = resolve_feishu_group_strict(project)
    except FeishuGroupResolutionError:
        return None
    return group_id


# ── Nonce & report building ──────────────────────────────────────────

def stable_dispatch_nonce(project: str, lane: str, task_id: str) -> str:
    seed = f"{project}:{lane}:{task_id}".encode("utf-8")
    return hashlib.sha1(seed).hexdigest()[:8]


def sanitize_report_value(value: str) -> str:
    return " ".join(str(value).split()).strip()


def sanitize_human_summary(value: str) -> str:
    lines = [" ".join(line.split()).strip() for line in str(value).splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def build_delegation_report_text(
    *,
    project: str,
    lane: str,
    task_id: str,
    dispatch_nonce: str,
    report_status: str,
    decision_hint: str,
    user_gate: str,
    next_action: str,
    summary: str,
    human_summary: str | None = None,
) -> str:
    if lane not in VALID_DELEGATION_LANES:
        raise ValueError(f"invalid delegation lane: {lane}")
    if report_status not in VALID_DELEGATION_REPORT_STATUSES:
        raise ValueError(f"invalid delegation report_status: {report_status}")
    if decision_hint not in VALID_DELEGATION_DECISION_HINTS:
        raise ValueError(f"invalid delegation decision_hint: {decision_hint}")
    if user_gate not in VALID_DELEGATION_USER_GATES:
        raise ValueError(f"invalid delegation user_gate: {user_gate}")
    if next_action not in VALID_DELEGATION_NEXT_ACTIONS:
        raise ValueError(f"invalid delegation next_action: {next_action}")

    ordered_fields = [
        ("project", sanitize_report_value(project)),
        ("lane", sanitize_report_value(lane)),
        ("task_id", sanitize_report_value(task_id)),
        ("dispatch_nonce", sanitize_report_value(dispatch_nonce)),
        ("report_status", sanitize_report_value(report_status)),
        ("decision_hint", sanitize_report_value(decision_hint)),
        ("user_gate", sanitize_report_value(user_gate)),
        ("next_action", sanitize_report_value(next_action)),
        ("summary", sanitize_report_value(summary)),
    ]
    lines = [f"[{DELEGATION_REPORT_HEADER}]"]
    lines.extend(f"{key}={value}" for key, value in ordered_fields)
    lines.append(f"[/{DELEGATION_REPORT_HEADER}]")
    human = sanitize_human_summary(human_summary or "")
    if human:
        lines.extend(["", human])
    return "\n".join(lines)


# ── Auth & CLI helpers ───────────────────────────────────────────────

def _lark_cli_real_home() -> str:
    """Return the REAL user home for lark-cli, bypassing any seat runtime isolation.

    lark-cli stores config at $HOME/.lark-cli/ and auth tokens at
    $HOME/Library/Application Support/lark-cli/. These are user-level,
    not seat-level. When a seat runs with an isolated HOME (ClawSeat
    runtime identity), we must restore the real user HOME so lark-cli
    can find its config and tokens.

    Shares resolution logic with _real_user_home(); the .lark-cli canary
    inside _real_user_home() makes this identical for lark-cli callers.
    """
    return str(_real_user_home())


def _lark_cli_env() -> dict[str, str | None]:
    # NOTE: do NOT pass OPENCLAW_HOME to lark-cli. Lark-cli manages its own
    # config at ~/.lark-cli/config.json (anchored to the real user HOME) and
    # setting OPENCLAW_HOME causes it to mis-resolve its config directory,
    # breaking auth checks even when a valid bot token exists.
    return {
        "HOME": _lark_cli_real_home(),
        "OPENCLAW_HOME": None,
    }


def _lark_cli_cwd() -> str:
    return _lark_cli_real_home()


def _normalize_lark_identity(identity: str | None) -> str:
    value = (identity or "auto").strip().lower()
    if value not in {"user", "bot", "auto"}:
        raise ValueError(f"invalid lark-cli identity: {identity!r}")
    return value


# ── Token lifetime / keepalive constants ─────────────────────────────
#
# Feishu user OAuth:
#   access_token  lifetime = 2h, auto-refreshed by lark-cli
#   refresh_token lifetime = 7d  (rotates on each refresh; grantedAt resets)
#   hard ceiling  = 365d from ORIGINAL user consent (Feishu server-side,
#                   error 20037 forces a fresh device-flow login).
#                   We do NOT try to predict this proactively because
#                   lark-cli's `grantedAt` reflects the current
#                   refresh_token's grant time, not the original consent
#                   — any "days-remaining" estimate from that field is
#                   always ≥ the real remaining, i.e. would warn LATE.
#                   Reactive handling via _classify_send_failure covers it.
#
# To keep a user session alive for long-idle automation we:
#   1. treat `needs_refresh` as ok (lark-cli auto-refreshes on next call)
#   2. if grantedAt is older than KEEPALIVE_DAYS, force a refresh via a
#      cheap UAT-authenticated API call before the 7d idle window closes
REFRESH_KEEPALIVE_DAYS = 5.0


def _parse_iso_ts(ts: str) -> datetime.datetime | None:
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _days_since(ts: datetime.datetime | None) -> float | None:
    if ts is None:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.timezone.utc)
    return (now - ts).total_seconds() / 86400.0


def _read_lark_auth_status(
    lark_cli: str,
    *,
    identity: str = "auto",
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Run `lark-cli auth status` once. Return (auth_info, error_payload)."""
    normalized = _normalize_lark_identity(identity)
    cmd = [lark_cli]
    if normalized != "auto":
        cmd.extend(["--as", normalized])
    cmd.extend(["auth", "status"])
    result = run_command_with_env(
        cmd,
        cwd=_lark_cli_cwd(),
        env=_lark_cli_env(),
    )
    # Workaround for lark-cli versions that don't support `--as bot/user`.
    # If the flag is unknown, retry without it — lark-cli will default to bot.
    if result.returncode != 0 and normalized != "auto" and "unknown flag" in result.stderr.lower():
        fallback_cmd = [lark_cli, "auth", "status"]
        result = run_command_with_env(
            fallback_cmd,
            cwd=_lark_cli_cwd(),
            env=_lark_cli_env(),
        )
    if result.returncode != 0:
        return None, {
            "status": "error",
            "reason": (
                f"lark-cli auth status failed (rc={result.returncode}, "
                f"identity={normalized}): {result.stderr.strip()}"
            ),
            "fix": "lark-cli auth login",
        }
    stdout = result.stdout.strip()
    try:
        return json.loads(stdout), None
    except (ValueError, TypeError):
        return None, {
            "status": "error",
            "reason": f"unexpected lark-cli auth output: {stdout[:200]}",
            "fix": "lark-cli auth login",
        }


def _keepalive_ping(lark_cli: str) -> bool:
    """Force a token refresh via a cheap UAT-authenticated API call.

    lark-cli's uat_client refreshes the access_token (and rotates the
    refresh_token, resetting its 7d expiry) whenever a UAT request is
    made while tokenStatus is needs_refresh. Calling user_info is the
    cheapest such request — success is best-effort; errors are swallowed.
    """
    result = run_command_with_env(
        [lark_cli, "api", "GET", "/open-apis/authen/v1/user_info"],
        cwd=_lark_cli_cwd(),
        env=_lark_cli_env(),
    )
    return result.returncode == 0


def check_feishu_auth(*, keepalive: bool = False, identity: str = "auto") -> dict[str, str]:
    """Check lark-cli availability and auth token status.

    keepalive=True enables opportunistic token refresh: if grantedAt is
    older than REFRESH_KEEPALIVE_DAYS but still within the 7d refresh
    window, a light API call is issued to rotate the refresh_token before
    idle-expiry kicks in.

    Status values:
      ok            — safe to send; lark-cli will auto-refresh if needed
      expired       — refresh_token past 7d window; human re-auth required
      missing       — lark-cli not installed
      error         — unexpected (bad output / hard ceiling imminent)
    """
    lark_cli = shutil.which("lark-cli")
    if not lark_cli:
        return {
            "status": "missing",
            "reason": "lark-cli not found in PATH",
            "fix": "brew install larksuite/cli/lark-cli",
        }
    normalized = _normalize_lark_identity(identity)
    auth_info, err = _read_lark_auth_status(lark_cli, identity=normalized)
    if err is not None:
        return err
    if auth_info is None:
        return {
            "status": "error",
            "reason": "lark-cli auth status returned no info",
            "fix": "lark-cli auth login",
        }

    if keepalive:
        granted_at = _parse_iso_ts(auth_info.get("grantedAt", ""))
        age_days = _days_since(granted_at)
        if age_days is not None and age_days >= REFRESH_KEEPALIVE_DAYS:
            if _keepalive_ping(lark_cli):
                refreshed, err2 = _read_lark_auth_status(lark_cli, identity=normalized)
                if err2 is None and refreshed is not None:
                    auth_info = refreshed

    token_status = auth_info.get("tokenStatus", "unknown")
    identity = auth_info.get("identity", "unknown")
    user_name = auth_info.get("userName", "")

    if token_status == "valid":
        payload: dict[str, str] = {
            "status": "ok",
            "reason": "auth token is valid",
            "identity": auth_info.get("identity", normalized),
            "requested_as": normalized,
        }
        if user_name:
            payload["userName"] = user_name
        return payload

    if token_status == "needs_refresh":
        # Access token expired but refresh_token still valid — lark-cli will
        # auto-refresh on the next UAT call, so this is NOT a failure.
        payload = {
            "status": "ok",
            "reason": (
                "access_token expired; refresh_token still valid "
                "(lark-cli will auto-refresh on next API call)"
            ),
            "identity": auth_info.get("identity", normalized),
            "requested_as": normalized,
            "warning": "needs_refresh",
        }
        if user_name:
            payload["userName"] = user_name
        return payload

    if token_status == "expired":
        return {
            "status": "expired",
            "reason": "refresh_token past 7d window (no calls for >7 days)",
            "fix": "lark-cli auth login  (in a terminal with a browser)",
            "requested_as": normalized,
        }

    return {
        "status": "error",
        "reason": f"unexpected token status: {token_status}",
        "fix": "lark-cli auth login",
        "requested_as": normalized,
    }


def _classify_send_failure(stderr: str, *, identity: str = "user") -> tuple[str, str]:
    lower = stderr.lower()
    if "token" in lower and ("expired" in lower or "invalid" in lower or "refresh" in lower):
        return "auth_expired", "lark-cli auth login"
    if "permission" in lower or "scope" in lower or "forbidden" in lower:
        normalized = _normalize_lark_identity(identity)
        if normalized == "user":
            return "permission_denied", "ensure lark-cli has im:message.send_as_user scope for user identity"
        if normalized == "bot":
            return "permission_denied", "ensure lark-cli has im:message scope for bot identity"
        return (
            "permission_denied",
            "rerun with --as user or --as bot after verifying the matching scope "
            "(user: im:message.send_as_user; bot: im:message)",
        )
    if "not found" in lower or "no such" in lower or "404" in lower:
        return "group_not_found", "check that the group ID is correct and the bot is in the group"
    if "timeout" in lower or "connection" in lower or "network" in lower:
        return "network_error", "check network connectivity and retry"
    return "lark_cli_send_failed", "run `lark-cli auth status` to diagnose"


# ── Send functions ───────────────────────────────────────────────────

def send_feishu_user_message(
    message: str,
    *,
    group_id: str | None = None,
    project: str | None = None,
    pre_check_auth: bool = False,
    identity: str = "user",
) -> dict[str, str]:
    if os.environ.get("CLAWSEAT_FEISHU_ENABLED", "1") == "0":
        return {"status": "skipped", "reason": "CLAWSEAT_FEISHU_ENABLED=0"}
    # Allow override via env var for smoke/one-shot dispatch
    identity = os.environ.get("FEISHU_SENDER_MODE", identity)
    normalized = _normalize_lark_identity(identity)
    payload: dict[str, str] = {"message": message.strip()}
    resolved_source = "explicit:group_id" if group_id else ""
    resolved_group_id = (group_id or "").strip()
    if not resolved_group_id:
        # No explicit override — require a project and resolve strictly.
        try:
            resolved_group_id, resolved_source = resolve_feishu_group_strict(project or "")
        except FeishuGroupResolutionError as exc:
            payload["status"] = "failed"
            payload["reason"] = "no_project_binding"
            payload["detail"] = str(exc)
            payload["project"] = str(project or "")
            payload["attempted_sources"] = "|".join(exc.attempted_sources)
            payload["fix"] = (
                "pass --chat-id, set CLAWSEAT_FEISHU_GROUP_ID, or create "
                "~/.agents/tasks/<project>/PROJECT_BINDING.toml "
                "(C1 guardrail — refuse to guess group)"
            )
            return payload
    payload["group_id"] = resolved_group_id
    payload["group_source"] = resolved_source
    lark_cli = shutil.which("lark-cli")
    if not lark_cli:
        payload["reason"] = "lark_cli_missing"
        payload["fix"] = "brew install larksuite/cli/lark-cli"
        return payload
    if pre_check_auth:
        auth = PLACEHOLDER(keepalive=True, identity=normalized)
        if auth["status"] != "ok":
            payload["status"] = "failed"
            payload["reason"] = f"auth_{auth['status']}"
            payload["fix"] = auth.get("fix", "lark-cli auth login")
            payload["auth_detail"] = auth.get("reason", "")
            return payload
    send_cmd = [lark_cli]
    if normalized != "auto":
        send_cmd.extend(["--as", normalized])
    send_cmd.extend(["im", "+messages-send"])
    send_cmd.extend(["--chat-id", resolved_group_id, "--text", message])
    result = run_command_with_env(
        send_cmd,
        cwd=_lark_cli_cwd(),
        env=_lark_cli_env(),
    )
    payload["transport"] = f"lark-cli-{normalized}"
    payload["returncode"] = str(result.returncode)
    if result.stdout.strip():
        payload["stdout"] = result.stdout.strip()
    if result.stderr.strip():
        payload["stderr"] = result.stderr.strip()
    if result.returncode == 0:
        payload["status"] = "sent"
    else:
        payload["status"] = "failed"
        reason, fix = _classify_send_failure(result.stderr, identity=normalized)
        payload["reason"] = reason
        payload["fix"] = fix
    return payload


def legacy_feishu_group_broadcast_enabled() -> bool:
    value = os.environ.get("CLAWSEAT_ENABLE_LEGACY_FEISHU_BROADCAST")
    if value is None:
        value = os.environ.get("OPENCLAW_ENABLE_LEGACY_FEISHU_BROADCAST")
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def broadcast_feishu_group_message(
    message: str,
    *,
    group_id: str | None = None,
    project: str | None = None,
) -> dict[str, str]:
    if os.environ.get("CLAWSEAT_FEISHU_ENABLED", "1") == "0":
        return {"status": "skipped", "reason": "CLAWSEAT_FEISHU_ENABLED=0"}
    payload: dict[str, str] = {"message": message.strip()}
    resolved_source = "explicit:group_id" if group_id else ""
    resolved_group_id = (group_id or "").strip()
    if not resolved_group_id:
        try:
            resolved_group_id, resolved_source = resolve_feishu_group_strict(project or "")
        except FeishuGroupResolutionError as exc:
            payload["status"] = "failed"
            payload["reason"] = "no_project_binding"
            payload["detail"] = str(exc)
            payload["project"] = str(project or "")
            payload["attempted_sources"] = "|".join(exc.attempted_sources)
            payload["fix"] = (
                "create ~/.agents/tasks/<project>/PROJECT_BINDING.toml or "
                "add feishu_group_id to WORKSPACE_CONTRACT.toml "
                "(C1 guardrail — refuse to guess group)"
            )
            return payload
    payload["group_id"] = resolved_group_id
    payload["group_source"] = resolved_source
    if not legacy_feishu_group_broadcast_enabled():
        payload["reason"] = "legacy_group_broadcast_disabled"
        return payload
    if not OPENCLAW_FEISHU_SEND_SH.exists():
        payload["reason"] = "feishu_send_script_missing"
        payload["send_script"] = str(OPENCLAW_FEISHU_SEND_SH)
        return payload
    result = run_command_with_env(
        ["bash", str(OPENCLAW_FEISHU_SEND_SH), "--target",
         f"group:{resolved_group_id}", message],
        cwd=OPENCLAW_HOME,
        env={"HOME": str(AGENT_HOME)},
    )
    payload["send_script"] = str(OPENCLAW_FEISHU_SEND_SH)
    payload["returncode"] = str(result.returncode)
    if result.stdout.strip():
        payload["stdout"] = result.stdout.strip()
    if result.stderr.strip():
        payload["stderr"] = result.stderr.strip()
    if result.returncode == 0:
        payload["status"] = "sent"
    else:
        payload["status"] = "failed"
        payload["reason"] = "feishu_send_failed"
    return payload
