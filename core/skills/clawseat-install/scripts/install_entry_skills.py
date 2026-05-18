#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]

# Resolve via core/lib/real_home — bypasses isolated/sandbox HOME so symlinks
# land under the real user's ~/.claude and ~/.codex, not the harness sandbox.
_CORE_LIB = REPO_ROOT / "core" / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))
from real_home import real_user_home  # noqa: E402

HOME = real_user_home()
RUNTIME_SKILL_ROOTS = {
    "claude": HOME / ".claude" / "skills",
    "codex": HOME / ".codex" / "skills",
}
ENTRY_SKILLS = {
    "clawseat": REPO_ROOT / "core" / "skills" / "clawseat",
    "cs": REPO_ROOT / "core" / "skills" / "cs",
    "clawseat-install": REPO_ROOT / "core" / "skills" / "clawseat-install",
    "clawseat-ancestor": REPO_ROOT / "core" / "skills" / "clawseat-ancestor",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install ClawSeat entry skills into agent skill directories."
    )
    parser.add_argument(
        "--runtime",
        action="append",
        choices=sorted(RUNTIME_SKILL_ROOTS),
        help="Install only for the selected runtime. Defaults to all supported runtimes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the symlink actions without modifying the filesystem.",
    )
    return parser.parse_args()


def ensure_symlink(destination: Path, source: Path, *, dry_run: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        current = destination.resolve()
        if current == source.resolve():
            print(f"already_installed: {destination} -> {source}")
            return
        if dry_run:
            print(f"would_replace_symlink: {destination} -> {source}")
            return
        destination.unlink()
    elif destination.exists():
        raise RuntimeError(
            f"refusing to overwrite non-symlink path: {destination}. Move it away first."
        )
    if dry_run:
        print(f"would_install: {destination} -> {source}")
        return
    destination.symlink_to(source)
    print(f"installed: {destination} -> {source}")


def main() -> int:
    args = parse_args()
    runtimes = args.runtime or list(RUNTIME_SKILL_ROOTS)
    for runtime in runtimes:
        skill_root = RUNTIME_SKILL_ROOTS[runtime]
        for skill_name, source in ENTRY_SKILLS.items():
            ensure_symlink(skill_root / skill_name, source, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
