"""ClawSeat v3 config proposal render validator.

Per spec §16.7.2 — install.sh runs this before rendering project.toml.
Any violation → install.sh exits non-zero with stderr violations list.

Validates:
- tool/auth_mode/provider enum
- (tool, role) Gemini blacklist per §6.4
- proposal_status == approved + operator_approved_ts non-null
- role values exist in skill catalog (best-effort; warns if catalog missing)

See spec §16.7 (install-spec-2026-05-13-clawseat-v3-multi-team-protocol.md).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib  # noqa: F401 — kept for symmetry
else:  # pragma: no cover
    pass

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover — PyYAML is a hard dep in ClawSeat runtime
    yaml = None  # type: ignore


VALID_TOOL = frozenset({"claude", "codex", "gemini"})
VALID_AUTH_MODE = frozenset({"oauth", "oauth_token", "api"})
VALID_PROVIDER = frozenset({"anthropic", "openai", "google", "minimax"})

# Known role catalog (post-review fix #2; spec §16.7.2 role catalog validation).
# Source of truth: planner/builder/reviewer/patrol are the original 4 specialist
# roles; v3 adds designer-image, designer-creative, content-narrative for the
# multi-team workflow. Memory is excluded — it's never a worker.
KNOWN_ROLES = frozenset(
    {
        "planner",
        "builder",
        "reviewer",
        "patrol",
        "designer",
        "designer-image",
        "designer-creative",
        "content-narrative",
    }
)

# §6.4 — (tool, role) blacklist; violation rejects render
GEMINI_BLACKLIST_ROLES = frozenset(
    {
        "memory",
        "reviewer",
        # backend / engine / business-logic builder is a category, not a literal role.
        # Phase 1 enforces via explicit role names; capability-based check is Phase 4.
    }
)
CODEX_BLACKLIST_ROLES = frozenset(
    {
        "memory",  # main memory long-context requirement
    }
)
MINIMAX_BLACKLIST_ROLES = frozenset(
    {
        "builder",
        "reviewer",
        "memory",
        # patrol/test-runner is allowed (specific purpose)
    }
)


class ProposalValidationError(RuntimeError):
    """Raised when one or more proposals fail validation."""

    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__(
            f"{len(violations)} proposal validation violation(s):\n  - "
            + "\n  - ".join(violations)
        )


@dataclass
class ValidationReport:
    proposal_file: Path
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML required to validate proposals")
    text = path.read_text(encoding="utf-8")
    # Strip leading frontmatter if present (---...---), then parse rest as YAML
    if text.startswith("---\n"):
        # Find the closing ---
        end = text.find("\n---\n", 4)
        if end == -1:
            end = text.find("\n---", 4)
        if end != -1:
            text = text[4:end]
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise RuntimeError(f"{path}: top-level YAML must be a mapping")
    return data


def _check_seat(
    seat: dict[str, Any],
    proposal_file: Path,
    seat_idx: int,
) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    warnings: list[str] = []
    seat_ctx = f"{proposal_file.name} seat[{seat_idx}]"

    role = str(seat.get("role") or "").strip()
    tool = str(seat.get("tool") or "").strip()
    auth_mode = str(seat.get("auth_mode") or "").strip()
    provider = str(seat.get("provider") or "").strip()

    if not role:
        violations.append(f"{seat_ctx}: missing required 'role'")
    elif role not in KNOWN_ROLES:
        # post-review fix #2: role catalog enforcement
        violations.append(
            f"{seat_ctx}: role={role!r} not in known catalog "
            f"{sorted(KNOWN_ROLES)}. Add to KNOWN_ROLES if intentional new role."
        )
    if tool not in VALID_TOOL:
        violations.append(
            f"{seat_ctx}: tool={tool!r} not in {sorted(VALID_TOOL)}"
        )
    if auth_mode not in VALID_AUTH_MODE:
        violations.append(
            f"{seat_ctx}: auth_mode={auth_mode!r} not in {sorted(VALID_AUTH_MODE)}"
        )
    if provider not in VALID_PROVIDER:
        violations.append(
            f"{seat_ctx}: provider={provider!r} not in {sorted(VALID_PROVIDER)}"
        )

    # §6.4 blacklist
    if tool == "gemini" and role in GEMINI_BLACKLIST_ROLES:
        violations.append(
            f"{seat_ctx}: §6.4 Gemini blacklist — role={role!r} not allowed for gemini"
        )
    if tool == "codex" and role in CODEX_BLACKLIST_ROLES:
        violations.append(
            f"{seat_ctx}: §6.4 Codex blacklist — role={role!r} not allowed for codex"
        )
    if (
        tool == "claude"
        and provider == "minimax"
        and role in MINIMAX_BLACKLIST_ROLES
    ):
        violations.append(
            f"{seat_ctx}: §6.4 Minimax-mode blacklist — role={role!r} not allowed"
        )

    if "rationale" not in seat or not str(seat.get("rationale") or "").strip():
        warnings.append(
            f"{seat_ctx}: §16.4 requires 'rationale' field explaining tool choice"
        )

    return violations, warnings


def validate_proposal_file(path: Path | str) -> ValidationReport:
    """Validate one approved config yaml. Returns ValidationReport (caller decides)."""
    p = Path(path)
    report = ValidationReport(proposal_file=p)

    if not p.exists():
        report.violations.append(f"{p.name}: file not found")
        return report

    try:
        data = _load_yaml(p)
    except Exception as exc:  # noqa: BLE001 - yaml/io errors surfaced as violations
        report.violations.append(f"{p.name}: parse error: {exc}")
        return report

    status = str(data.get("proposal_status") or "").strip()
    if status != "approved":
        report.violations.append(
            f"{p.name}: proposal_status={status!r} (must be 'approved' to render)"
        )

    if not data.get("operator_approved_ts"):
        report.violations.append(
            f"{p.name}: operator_approved_ts is empty/null"
        )

    if "estimated_monthly_cost_usd" not in data:
        report.warnings.append(
            f"{p.name}: §16.4 requires estimated_monthly_cost_usd"
        )

    seats = data.get("seats") or []
    if not isinstance(seats, list) or not seats:
        report.violations.append(f"{p.name}: 'seats' must be non-empty list")
    else:
        for idx, seat in enumerate(seats):
            if not isinstance(seat, dict):
                report.violations.append(
                    f"{p.name} seat[{idx}]: must be a mapping"
                )
                continue
            v, w = _check_seat(seat, p, idx)
            report.violations.extend(v)
            report.warnings.extend(w)

    return report


def validate_proposal_dir(proposals_dir: Path | str) -> list[ValidationReport]:
    """Validate every *__approved.yaml in a directory. Returns list of reports."""
    d = Path(proposals_dir)
    if not d.exists():
        return []
    reports: list[ValidationReport] = []
    for yaml_file in sorted(d.glob("*__approved.yaml")):
        reports.append(validate_proposal_file(yaml_file))
    return reports


def assert_all_valid(proposals_dir: Path | str) -> None:
    """Raise ProposalValidationError if any approved config has violations.

    install.sh calls this before rendering project.toml. Warnings do not block.
    """
    reports = validate_proposal_dir(proposals_dir)
    all_violations: list[str] = []
    for r in reports:
        all_violations.extend(r.violations)
    if all_violations:
        raise ProposalValidationError(all_violations)


def main(argv: list[str] | None = None) -> int:
    """CLI entry: python3 proposal_validator.py <proposals_dir>."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate ClawSeat v3 approved config proposals before render."
    )
    parser.add_argument("proposals_dir", help="Directory containing *__approved.yaml")
    parser.add_argument(
        "--warnings-as-errors",
        action="store_true",
        help="Treat warnings as violations (strict mode).",
    )
    args = parser.parse_args(argv)

    reports = validate_proposal_dir(args.proposals_dir)
    if not reports:
        print(f"No *__approved.yaml found in {args.proposals_dir}", file=sys.stderr)
        return 1

    any_violation = False
    for r in reports:
        if r.violations:
            any_violation = True
            print(f"FAIL {r.proposal_file.name}", file=sys.stderr)
            for v in r.violations:
                print(f"  ✗ {v}", file=sys.stderr)
        else:
            print(f"PASS {r.proposal_file.name}")
        for w in r.warnings:
            if args.warnings_as_errors:
                any_violation = True
                print(f"  ✗ (strict) {w}", file=sys.stderr)
            else:
                print(f"  ⚠ {w}", file=sys.stderr)

    return 1 if any_violation else 0


if __name__ == "__main__":
    raise SystemExit(main())
