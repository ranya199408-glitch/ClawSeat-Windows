"""Auto-provision per-seat runtime HOME symlinks (C4).

When a seat launches with an isolated HOME (``<runtime_dir>/home/``),
user-level artifacts like ``~/.lark-cli/`` (Feishu auth tokens) and
``~/.openclaw/`` (OpenClaw workspace contracts + session registry)
disappear from the seat's view. The _feishu module works around this
with ``_real_user_home`` resolution at runtime, but plenty of other
tooling (and the operator reading via ``env HOME=... ls``) just sees
the bare sandbox.

This module creates idempotent symlinks from the sandbox HOME back to
the real operator's dotfiles so every seat "feels right" without
any manual post-boot fixup. The P1 ask from the user:

    runtime home 自动补齐 — 不应该再靠手工给每个 seat
    补符号链接。

Rules (all idempotent, safe to re-run):

  - Only create symlinks whose real-home target actually exists — never
    leave dangling symlinks that will confuse later readers.
  - If the sandbox HOME already has the correct symlink, no-op.
  - If it has the wrong symlink (points elsewhere), fix it.
  - If it has a real file/directory, **leave it alone** and return a
    warning — the operator may have intentionally isolated that seat
    from the real home, and we must not destroy their work.
  - All operations are defensive: any OSError is caught and surfaced
    as a structured result rather than killing the seat launch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# Canonical list of dotfiles that seats need to see back from their
# sandbox HOME. Add new entries here when a new tool-at-real-home
# dependency shows up.
RUNTIME_HOME_LINK_NAMES: tuple[str, ...] = (
    ".lark-cli",
    ".openclaw",
)


@dataclass
class LinkAction:
    name: str                 # e.g. ".lark-cli"
    status: str               # "created" | "already_correct" | "fixed" | "skipped_real_target" | "skipped_missing_source" | "error"
    sandbox_path: Path
    target: Path | None = None
    detail: str = ""


@dataclass
class LinkResult:
    sandbox_home: Path
    real_home: Path
    actions: list[LinkAction] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"runtime-home-links sandbox={self.sandbox_home} real={self.real_home}"
        ]
        for action in self.actions:
            lines.append(f"  [{action.status}] {action.name} -> {action.target or '(n/a)'}")
            if action.detail:
                lines.append(f"      detail: {action.detail}")
        return "\n".join(lines)

    @property
    def errors(self) -> list[LinkAction]:
        return [a for a in self.actions if a.status == "error"]


def ensure_runtime_home_links(
    sandbox_home: Path,
    real_home: Path,
    *,
    names: Iterable[str] = RUNTIME_HOME_LINK_NAMES,
) -> LinkResult:
    """Create/repair symlinks from ``sandbox_home/<name>`` to ``real_home/<name>``.

    Idempotent. Never destroys real files at the sandbox target. Returns
    a :class:`LinkResult` describing every action (created/fixed/skipped/error)
    so the caller can log a one-line status without deciding policy here.
    """
    sandbox_home = Path(sandbox_home)
    real_home = Path(real_home)
    result = LinkResult(sandbox_home=sandbox_home, real_home=real_home)

    if sandbox_home.resolve() == real_home.resolve():
        # No sandbox isolation in play — no symlinks to create.
        for name in names:
            result.actions.append(
                LinkAction(
                    name=name,
                    status="already_correct",
                    sandbox_path=sandbox_home / name,
                    target=real_home / name,
                    detail="sandbox_home == real_home",
                )
            )
        return result

    for name in names:
        action = _process_one_link(sandbox_home, real_home, name)
        result.actions.append(action)
    return result


def _process_one_link(sandbox_home: Path, real_home: Path, name: str) -> LinkAction:
    sandbox_path = sandbox_home / name
    target = real_home / name

    if not target.exists():
        return LinkAction(
            name=name,
            status="skipped_missing_source",
            sandbox_path=sandbox_path,
            target=target,
            detail=f"{target} does not exist on the real home",
        )

    if sandbox_path.is_symlink():
        try:
            current = sandbox_path.readlink()
        except OSError as exc:
            return LinkAction(
                name=name,
                status="error",
                sandbox_path=sandbox_path,
                target=target,
                detail=f"readlink failed: {exc}",
            )
        # Compare against target (not target.resolve) so a symlink-of-symlink
        # real_home is still recognized as the expected shape.
        if Path(current) == target:
            return LinkAction(
                name=name, status="already_correct",
                sandbox_path=sandbox_path, target=target,
            )
        # Wrong symlink — repair in place.
        try:
            sandbox_path.unlink()
            sandbox_path.symlink_to(target)
            return LinkAction(
                name=name, status="fixed",
                sandbox_path=sandbox_path, target=target,
                detail=f"previous target was {current}",
            )
        except OSError as exc:
            return LinkAction(
                name=name, status="error",
                sandbox_path=sandbox_path, target=target,
                detail=f"failed to repair symlink: {exc}",
            )

    if sandbox_path.exists():
        # A real file or directory lives where we wanted to put a symlink.
        # Refuse to touch it; the operator put something there on purpose.
        return LinkAction(
            name=name, status="skipped_real_target",
            sandbox_path=sandbox_path, target=target,
            detail=(
                f"{sandbox_path} exists as a non-symlink; leaving it alone so "
                "seat-local state is not destroyed. Remove it manually if "
                "you want the runtime_home_links helper to create the symlink."
            ),
        )

    try:
        sandbox_path.parent.mkdir(parents=True, exist_ok=True)
        sandbox_path.symlink_to(target)
    except OSError as exc:
        return LinkAction(
            name=name, status="error",
            sandbox_path=sandbox_path, target=target,
            detail=f"symlink_to failed: {exc}",
        )
    return LinkAction(
        name=name, status="created",
        sandbox_path=sandbox_path, target=target,
    )
