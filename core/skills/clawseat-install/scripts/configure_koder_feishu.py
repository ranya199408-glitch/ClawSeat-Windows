#!/usr/bin/env python3
"""configure_koder_feishu.py — auto-configure openclaw agent Feishu settings.

Flips `requireMention=false` on an OpenClaw agent (and optionally a specific
group binding) so the agent responds to Feishu messages without @mention.

Called from the canonical install flow:
- P3.3 (after koder overlay + init_koder): --agent <chosen> (account-level)
- P4.2 (after bind_project_to_group): --agent <chosen> --group-id <oc_xxx>

Safety:
- Atomic write via tempfile + rename
- Backup to openclaw.json.bak.<ts> before mutation
- Only touches channels.feishu.accounts.<agent> — does not add _comment_*
  fields (would trigger OpenClaw schema auto-reset per prior incident)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path


def _real_user_home() -> Path:
    import os
    try:
        import pwd
        pw = pwd.getpwuid(os.getuid())
        if pw and pw.pw_dir:
            return Path(pw.pw_dir)
    except (ImportError, KeyError):
        pass
    return Path.home()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--agent", required=True, help="OpenClaw agent name (e.g. 'yu', 'mor').")
    p.add_argument("--group-id", help="Feishu group id (oc_<alnum>). If set, applies requireMention at group level under accounts.<agent>.groups.")
    p.add_argument("--openclaw-home", default=None, help="Override ~/.openclaw. Default: real user HOME's .openclaw/")
    p.add_argument("--dry-run", action="store_true", help="Print the diff without writing.")
    return p.parse_args()


def load_config(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"error: openclaw.json not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_account(config: dict, agent: str) -> dict:
    accounts = config.get("channels", {}).get("feishu", {}).get("accounts", {})
    if agent not in accounts:
        available = list(accounts.keys())
        raise SystemExit(
            f"error: OpenClaw account '{agent}' not found. Available: {available}"
        )
    return accounts[agent]


def patch(account: dict, group_id: str | None) -> bool:
    """Return True if config changed."""
    changed = False
    if group_id:
        groups = account.setdefault("groups", {})
        entry = groups.setdefault(group_id, {})
        if entry.get("requireMention") is not False:
            entry["requireMention"] = False
            changed = True
    else:
        if account.get("requireMention") is not False:
            account["requireMention"] = False
            changed = True
    return changed


def atomic_write(path: Path, content: str) -> None:
    tmp = tempfile.NamedTemporaryFile(
        "w", dir=str(path.parent), delete=False, encoding="utf-8", suffix=".tmp"
    )
    try:
        tmp.write(content)
        tmp.flush()
        import os
        os.fsync(tmp.fileno())
        tmp.close()
        Path(tmp.name).replace(path)
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise


def main() -> int:
    args = parse_args()
    home = Path(args.openclaw_home).expanduser() if args.openclaw_home else (_real_user_home() / ".openclaw")
    config_path = home / "openclaw.json"

    config = load_config(config_path)
    account = ensure_account(config, args.agent)

    before = json.dumps(account, indent=2, ensure_ascii=False)
    changed = patch(account, args.group_id)
    after = json.dumps(account, indent=2, ensure_ascii=False)

    scope = f"group '{args.group_id}' under" if args.group_id else "account"
    if not changed:
        print(f"ok: {scope} '{args.agent}' already has requireMention=false (no change)")
        return 0

    if args.dry_run:
        print(f"dry-run: would set requireMention=false on {scope} '{args.agent}'")
        print("--- before ---")
        print(before)
        print("--- after ---")
        print(after)
        return 0

    # backup then write
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = config_path.with_suffix(f".json.bak.{ts}")
    shutil.copy2(config_path, backup)
    atomic_write(config_path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")

    print(f"configured: requireMention=false on {scope} '{args.agent}'")
    print(f"backup: {backup}")
    print()
    print("next: restart the OpenClaw gateway for the change to take effect:")
    print("  pnpm --dir ~/.openclaw/apps/gateway openclaw gateway restart")
    print("  (or equivalent exec command — gateway/nodes tools are not reachable")
    print("   from inside a Feishu session, use shell exec.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
