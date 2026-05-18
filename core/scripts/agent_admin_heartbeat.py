from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]

def detect_claude_onboarding_step(text: str, markers: list[tuple[str, str]]) -> str | None:
    for marker, step in markers:
        if marker in text:
            return step
    return None


def is_claude_onboarding_text(text: str, markers: list[tuple[str, str]]) -> bool:
    return detect_claude_onboarding_step(text, markers) is not None


def capture_session_pane_text(session_name: str) -> str:
    proc = subprocess.run(
        ["tmux", "capture-pane", "-pt", f"{session_name}:0.0", "-S", "-200"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else ""


def wait_for_claude_ui_state(
    session: Any,
    *,
    markers: list[tuple[str, str]],
    timeout_seconds: int = 8,
    stable_reads_required: int = 2,
) -> tuple[str, str | None, bool]:
    last_text = ""
    stable_reads = 0
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        pane_text = capture_session_pane_text(session.session)
        onboarding_step = detect_claude_onboarding_step(pane_text, markers)
        if onboarding_step is not None:
            return pane_text, onboarding_step, False
        if pane_text.strip():
            if pane_text == last_text:
                stable_reads += 1
            else:
                last_text = pane_text
                stable_reads = 1
            if stable_reads >= stable_reads_required:
                return pane_text, None, True
        time.sleep(1)

    final_text = last_text or capture_session_pane_text(session.session)
    return final_text, detect_claude_onboarding_step(final_text, markers), False


def extract_cron_create_success(text: str) -> dict[str, str] | None:
    legacy_matches = list(
        re.finditer(r"Scheduled(?: recurring job)? ([A-Za-z0-9-]+) \(([^)]+)\)", text)
    )
    if legacy_matches:
        match = legacy_matches[-1]
        return {
            "job_id": match.group(1),
            "schedule": match.group(2),
            "line": match.group(0),
        }

    modern_matches = list(
        re.finditer(
            r"Heartbeat loop scheduled [—-] every (\d+) minute(?:s)?, cron job ([A-Za-z0-9-]+)\.",
            text,
        )
    )
    if not modern_matches:
        return None
    match = modern_matches[-1]
    interval = int(match.group(1))
    schedule = "Every minute" if interval == 1 else f"Every {interval} minutes"
    return {
        "job_id": match.group(2),
        "schedule": schedule,
        "line": match.group(0),
    }


def extract_scheduled_task_activity(text: str) -> dict[str, str] | None:
    matches = list(re.finditer(r"Running scheduled task \(([^)]+)\)", text))
    if not matches:
        return None
    match = matches[-1]
    return {
        "at": match.group(1),
        "line": match.group(0),
    }


def line_is_newer(after: str, before: str, line: str) -> bool:
    return after.count(line) > before.count(line)


def verify_heartbeat_install_from_pane(session: Any, previous_text: str) -> dict[str, str] | None:
    for attempt in range(12):
        if attempt:
            time.sleep(1)
        pane_text = capture_session_pane_text(session.session)
        success = extract_cron_create_success(pane_text)
        if success and line_is_newer(pane_text, previous_text, success["line"]):
            return {
                "verification_method": "cron_create_ack",
                "evidence": success["line"],
                "job_id": success["job_id"],
                "schedule": success["schedule"],
            }
    return None


def build_claude_loop_command(manifest: dict) -> str:
    interval = int(manifest.get("interval_minutes", 15))
    workspace = str(manifest.get("workspace", "")).strip()
    active_loop_owner = str(manifest.get("active_loop_owner", "planner")).strip() or "planner"
    heartbeat_md = f"{workspace}/HEARTBEAT.md" if workspace else "HEARTBEAT.md"
    heartbeat_manifest = (
        f"{workspace}/HEARTBEAT_MANIFEST.toml" if workspace else "HEARTBEAT_MANIFEST.toml"
    )
    prompt = (
        f"Read {heartbeat_md} and {heartbeat_manifest}. "
        "Follow HEARTBEAT.md exactly. "
        "Run the listed heartbeat commands as needed. "
        f"If there is no meaningful state change or no real reminder is needed for {active_loop_owner}, "
        "reply exactly HEARTBEAT_OK. "
        f"If there is a real stall or delivery-not-consumed condition, remind {active_loop_owner} only and do not take over dispatch."
    )
    return f"/loop {interval}m {prompt}"


# Claude-specific markers used ONLY by provision_session_heartbeat() to decide
# whether a Claude pane is still in first-run setup (cannot receive /loop yet).
# This table is intentionally Claude-only because heartbeat provisioning sends
# Claude /loop commands. Codex/Gemini seats still use the generic launcher; they
# simply skip this post-start heartbeat adapter.
#
# For start_seat's full claude/codex/gemini startup-readiness table, see
# core/skills/gstack-harness/scripts/_common.py :: CLAUDE_ONBOARDING_MARKERS
# (that is the single source of truth for seat-start detection).
#
# When you touch _common.py markers, also cross-check the Claude substrings
# here; tests/test_onboarding_markers.py verifies the Claude subset is in sync.
CLAUDE_ONBOARDING_MARKERS: tuple[tuple[str, str], ...] = (
    ("Let's get started.", "welcome"),
    ("Choose the text style", "text_style"),
    ("WARNING: Claude Code running in Bypass Permissions mode", "bypass_permissions"),
    ("Bypass Permissions mode", "bypass_permissions"),
    ("Accessing workspace:", "workspace_trust"),
    ("Quick safety check:", "workspace_trust"),
    ("Browser didn't open? Use the url below to sign in", "oauth_login"),
    ("Paste code here if prompted >", "oauth_code"),
    ("Login successful. Press Enter to continue", "oauth_continue"),
    ("OAuth error:", "oauth_error"),
    ("/theme", "theme_setup"),
)


@dataclass
class HeartbeatHooks:
    error_cls: type[Exception]
    send_and_verify_sh: str
    q: Callable[[str], str]
    q_array: Callable[[list[str]], str]
    ensure_dir: Callable[[Path], None]
    write_text: Callable[[Path, str], None]
    load_toml: Callable[[Path], dict]
    tmux_has_session: Callable[[str], bool]
    find_active_loop_owner: Callable[..., str | None]


class HeartbeatHandlers:
    def __init__(self, hooks: HeartbeatHooks) -> None:
        self.hooks = hooks

    def manifest_path(self, session: Any) -> Path:
        return Path(session.workspace) / "HEARTBEAT_MANIFEST.toml"

    def receipt_path(self, session: Any) -> Path:
        return Path(session.workspace) / "HEARTBEAT_RECEIPT.toml"

    def load_manifest(self, session: Any) -> dict | None:
        path = self.manifest_path(session)
        if not path.exists():
            return None
        return self.hooks.load_toml(path)

    def load_receipt(self, session: Any) -> dict | None:
        path = self.receipt_path(session)
        if not path.exists():
            return None
        return self.hooks.load_toml(path)

    def manifest_fingerprint(self, manifest: dict) -> str:
        encoded = json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def install_fingerprint(self, session: Any, manifest: dict) -> str:
        payload = {
            "tool": session.tool,
            "session": session.session,
            "command": build_claude_loop_command(manifest),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    # Heartbeat receipts are written with a `verified_at` timestamp but
    # the check path (receipt_matches_manifest) historically only
    # compared fingerprints, so a receipt written weeks ago was just as
    # valid as one from seconds ago (audit M17). We now require the
    # timestamp be within RECEIPT_VALID_FOR_SECONDS of now. Override via
    # CLAWSEAT_HEARTBEAT_RECEIPT_TTL_SECONDS for test/sandbox runs.
    RECEIPT_VALID_FOR_SECONDS = 24 * 3600  # 24 hours — matches the
                                           # schedule of the heartbeat
                                           # cron it's supposed to prove.

    def _receipt_ttl_seconds(self) -> int:
        override = os.environ.get("CLAWSEAT_HEARTBEAT_RECEIPT_TTL_SECONDS", "").strip()
        if override:
            try:
                value = int(override)
                if value > 0:
                    return value
            except ValueError:
                pass
        return self.RECEIPT_VALID_FOR_SECONDS

    def _receipt_is_fresh(self, receipt: dict) -> bool:
        raw = str(receipt.get("verified_at", "")).strip()
        if not raw:
            return False
        try:
            stamp = datetime.fromisoformat(raw)
        except ValueError:
            return False
        now = datetime.now(stamp.tzinfo) if stamp.tzinfo else datetime.now()
        try:
            age = (now - stamp).total_seconds()
        except (TypeError, ValueError):
            return False
        return 0 <= age <= self._receipt_ttl_seconds()

    def receipt_matches_manifest(self, receipt: dict | None, manifest: dict, session: Any) -> bool:
        if not receipt:
            return False
        if receipt.get("status") != "verified":
            return False
        if str(receipt.get("seat_id", "")) != session.engineer_id:
            return False
        if str(receipt.get("session", "")) != session.session:
            return False
        # Audit M17: a matching fingerprint is necessary but not sufficient;
        # a stale receipt (older than RECEIPT_VALID_FOR_SECONDS) no longer
        # counts as "verified" even when its fingerprint still matches.
        if not self._receipt_is_fresh(receipt):
            return False
        install_fingerprint = self.install_fingerprint(session, manifest)
        if str(receipt.get("install_fingerprint", "")) == install_fingerprint:
            return True
        return str(receipt.get("manifest_fingerprint", "")) == self.manifest_fingerprint(manifest)

    def write_receipt(
        self,
        session: Any,
        manifest: dict,
        *,
        verification_method: str,
        evidence: str,
        status: str = "verified",
        job_id: str = "",
        schedule: str = "",
    ) -> None:
        receipt_path = self.receipt_path(session)
        now = datetime.now().isoformat(timespec="seconds")
        lines = [
            "version = 2",
            f"seat_id = {self.hooks.q(session.engineer_id)}",
            f"project = {self.hooks.q(session.project)}",
            f"session = {self.hooks.q(session.session)}",
            f"status = {self.hooks.q(status)}",
            f"manifest_path = {self.hooks.q(str(self.manifest_path(session)))}",
            f"install_fingerprint = {self.hooks.q(self.install_fingerprint(session, manifest))}",
            f"manifest_fingerprint = {self.hooks.q(self.manifest_fingerprint(manifest))}",
            f"verified_at = {self.hooks.q(now)}",
            f"verification_method = {self.hooks.q(verification_method)}",
        ]
        if job_id:
            lines.append(f"job_id = {self.hooks.q(job_id)}")
        if schedule:
            lines.append(f"schedule = {self.hooks.q(schedule)}")
        if evidence:
            lines.append(f"evidence = {self.hooks.q(evidence)}")
        # C16: token usage measurement (best-effort; never fails the write)
        pct, source = self._measure_token_usage(session)
        if pct is not None:
            lines.append(f"token_usage_pct = {pct:.6f}")
        lines.append(f"token_usage_source = {self.hooks.q(source)}")
        lines.append(f"token_usage_measured_at = {self.hooks.q(now)}")
        lines.append("")
        self.hooks.write_text(receipt_path, "\n".join(lines))

    def _measure_token_usage(self, session: Any) -> tuple[float | None, str]:
        """Best-effort token usage heuristic. Never raises."""
        import os as _os
        env_pct = _os.environ.get("CC_CONTEXT_USAGE_PCT", "").strip()
        if env_pct:
            try:
                return (min(1.0, max(0.0, float(env_pct))), "cc_env")
            except ValueError:
                pass
        try:
            workspace = Path(getattr(session, "workspace", ""))
            candidates: list[Path] = []
            for base in [workspace / ".claude" / "projects"]:
                if base.exists():
                    candidates.extend(base.glob("*/*.jsonl"))
            if not candidates:
                return (None, "unknown")
            largest = max(candidates, key=lambda p: p.stat().st_size)
            model = str(getattr(session, "model", "")).strip()
            max_tok = 200_000
            if "1m" in model.lower() and "opus" in model.lower():
                max_tok = 1_000_000
            pct = min(1.0, largest.stat().st_size / (max_tok * 8))
            return (pct, "session_jsonl_size")
        except Exception:
            return (None, "unknown")

    def render_heartbeat_text(self, session: Any, project: Any, engineer: Any) -> str | None:
        # Heartbeat text rendering is project-adapter-specific.
        # No built-in adapters currently provide heartbeat text.
        return None

    def render_heartbeat_manifest_text(
        self,
        session: Any,
        project: Any,
        engineer: Any,
        *,
        project_engineers: dict[str, Any] | None = None,
        engineer_order: list[str] | None = None,
    ) -> str | None:
        # Heartbeat manifest rendering is project-adapter-specific.
        # No built-in adapters currently provide heartbeat manifests.
        return None

    def provision_session_heartbeat(
        self,
        session: Any,
        *,
        force: bool = False,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        if session.tool != "claude":
            return (
                False,
                f"{session.engineer_id}: heartbeat skipped for {session.tool} session "
                "(Claude /loop provisioning only)",
            )

        manifest = self.load_manifest(session)
        if not manifest:
            return False, f"{session.engineer_id}: no HEARTBEAT_MANIFEST.toml present"

        if not self.hooks.tmux_has_session(session.session):
            return False, f"{session.engineer_id}: session {session.session} is not running"

        pane_text, onboarding_step, pane_stable = wait_for_claude_ui_state(
            session,
            markers=list(CLAUDE_ONBOARDING_MARKERS),
        )
        if onboarding_step is not None:
            return (
                False,
                f"{session.engineer_id}: Claude onboarding still visible ({onboarding_step}); finish onboarding before provisioning heartbeat",
            )
        if not pane_stable:
            return (
                False,
                f"{session.engineer_id}: Claude UI is still settling; retry heartbeat provisioning after the TUI reaches a stable prompt",
            )

        receipt = self.load_receipt(session)
        if self.receipt_matches_manifest(receipt, manifest, session) and not force:
            return (
                False,
                f"{session.engineer_id}: heartbeat already verified in {self.receipt_path(session)}",
            )

        if not force:
            existing_ack = extract_cron_create_success(pane_text)
            receipt_job_id = str(receipt.get("job_id", "")) if receipt else ""
            receipt_install_fingerprint = str(receipt.get("install_fingerprint", "")) if receipt else ""
            if existing_ack and (
                not receipt
                or not receipt_install_fingerprint
                or existing_ack["job_id"] != receipt_job_id
            ):
                self.write_receipt(
                    session,
                    manifest,
                    verification_method="pane_cron_ack_reconcile",
                    evidence=existing_ack["line"],
                    job_id=existing_ack["job_id"],
                    schedule=existing_ack["schedule"],
                )
                return (
                    True,
                    f"{session.engineer_id}: reconciled existing heartbeat from pane ack into {self.receipt_path(session)}",
                )
            existing_activity = extract_scheduled_task_activity(pane_text)
            if existing_activity and not receipt:
                self.write_receipt(
                    session,
                    manifest,
                    verification_method="pane_activity_reconcile",
                    evidence=existing_activity["line"],
                )
                return (
                    True,
                    f"{session.engineer_id}: reconciled existing heartbeat activity into {self.receipt_path(session)}",
                )

        command = build_claude_loop_command(manifest)
        if dry_run:
            return True, command

        previous_text = pane_text
        result = subprocess.run(
            [self.hooks.send_and_verify_sh, session.session, command],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            detail = stderr or stdout or "unknown send failure"
            raise self.hooks.error_cls(
                f"Heartbeat provision failed for {session.engineer_id}: {detail}"
            )

        verification = verify_heartbeat_install_from_pane(session, previous_text)
        if verification:
            self.write_receipt(
                session,
                manifest,
                verification_method=verification["verification_method"],
                evidence=verification["evidence"],
                job_id=verification.get("job_id", ""),
                schedule=verification.get("schedule", ""),
            )
            detail = (
                f"{session.engineer_id}: heartbeat verified and recorded in {self.receipt_path(session)}"
            )
            return True, detail

        return (
            False,
            f"{session.engineer_id}: /loop command was sent but no verifiable install ack was observed; inspect {session.session} before treating heartbeat as installed",
        )
