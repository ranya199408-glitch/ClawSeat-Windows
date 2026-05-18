#!/usr/bin/env python3
"""spec_admin.py — task SPEC.md lifecycle helper.

Subcommands:
  create     Create a new SPEC.md from template under
             ~/.agents/memory/projects/<project>/spec/<task_id>/SPEC.md.
             Status starts at "drafting".
  show       Pretty-print a summary of the spec: status, AC table, recent
             amendments.
  lock       Transition status from "drafting" to "locked". After lock,
             any change must go through `amend`.
  amend      Append an amendment under spec/<task_id>/amendments/000N-<slug>.md
             and bump the SPEC.md version + last_amended_at + 变更历史 row.
             SPEC.md must already be in "locked" state.
  verify     Run all AC assert/script entries and report pass/fail per AC.
             Returns exit 0 only if every AC is passed or human-judged true.
  close      Transition status to "closed" after final acceptance.

Spec file layout:
  ~/.agents/memory/projects/<project>/spec/<task_id>/
  ├── SPEC.md                      ← contract (this script writes frontmatter)
  ├── amendments/
  │   └── 000N-<slug>.md
  └── acceptance/                  ← optional, holds AC scripts referenced by SPEC.md
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_PATH = _REPO_ROOT / "core" / "templates" / "SPEC.template.md"
_SPEC_BASE_ENV = "CLAWSEAT_SPEC_BASE"  # override for tests / sandbox

# ── frontmatter parsing ──────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n(.*)\Z", re.DOTALL)
_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*?)\s*$")

_VALID_STATUSES = {"drafting", "locked", "amending", "closed"}
_STATUS_DISPLAY = {
    "drafting": "📋 草稿中",
    "locked": "🔒 已锁定",
    "amending": "🔄 修订中",
    "closed": "✅ 已结案",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _spec_base() -> Path:
    override = os.environ.get(_SPEC_BASE_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".agents" / "memory" / "projects"


def _spec_dir(project: str, task_id: str) -> Path:
    return _spec_base() / project / "spec" / task_id


def _spec_path(project: str, task_id: str) -> Path:
    return _spec_dir(project, task_id) / "SPEC.md"


def _amendments_dir(project: str, task_id: str) -> Path:
    return _spec_dir(project, task_id) / "amendments"


@dataclass
class SpecDoc:
    path: Path
    frontmatter: dict[str, str]
    body: str

    @property
    def status(self) -> str:
        return self.frontmatter.get("status", "drafting")

    @property
    def version(self) -> str:
        return self.frontmatter.get("version", "0.1")

    def bump_version(self) -> str:
        cur = self.version
        if "." in cur:
            major, minor = cur.split(".", 1)
            try:
                return f"{major}.{int(minor) + 1}"
            except ValueError:
                pass
        try:
            return str(int(cur) + 1)
        except ValueError:
            return f"{cur}+1"


def _load_spec(path: Path) -> SpecDoc:
    if not path.exists():
        raise SystemExit(f"spec_admin: SPEC.md not found: {path}")
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise SystemExit(f"spec_admin: missing YAML frontmatter in {path}")
    frontmatter_raw, body = match.group(1), match.group(2)
    frontmatter: dict[str, str] = {}
    for line in frontmatter_raw.splitlines():
        kv = _KV_RE.match(line)
        if kv:
            frontmatter[kv.group(1)] = kv.group(2)
    return SpecDoc(path=path, frontmatter=frontmatter, body=body)


def _dump_spec(doc: SpecDoc) -> None:
    lines = ["---"]
    for key, value in doc.frontmatter.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    text = "\n".join(lines) + "\n" + doc.body
    doc.path.write_text(text, encoding="utf-8")


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9一-鿿]+", "-", text.strip()).strip("-")
    return cleaned.lower()[:48] or "amend"


# ── subcommands ──────────────────────────────────────────────────────────────


def cmd_create(args: argparse.Namespace) -> int:
    spec_dir = _spec_dir(args.project, args.task_id)
    spec_file = spec_dir / "SPEC.md"
    if spec_file.exists() and not args.force:
        print(f"spec_admin: SPEC.md already exists: {spec_file}", file=sys.stderr)
        print("  use --force to overwrite", file=sys.stderr)
        return 1
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "amendments").mkdir(exist_ok=True)
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    timestamp = _now_iso()
    rendered = (
        template
        .replace("{{TASK_ID}}", args.task_id)
        .replace("{{PROJECT}}", args.project)
        .replace("{{TITLE}}", args.title)
        .replace("{{TIMESTAMP}}", timestamp)
    )
    spec_file.write_text(rendered, encoding="utf-8")
    print(f"created: {spec_file}")
    print(f"  status: drafting ({_STATUS_DISPLAY['drafting']})")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    doc = _load_spec(_spec_path(args.project, args.task_id))
    print(f"spec_id : {doc.frontmatter.get('spec_id', args.task_id)}")
    print(f"project : {doc.frontmatter.get('project', args.project)}")
    print(f"version : {doc.version}")
    print(f"status  : {doc.status} ({_STATUS_DISPLAY.get(doc.status, doc.status)})")
    print(f"created : {doc.frontmatter.get('created_at', '-')}")
    print(f"amended : {doc.frontmatter.get('last_amended_at', '-')}")

    # Extract title from body
    body_lines = doc.body.lstrip().splitlines()
    if body_lines and body_lines[0].startswith("# "):
        print(f"title   : {body_lines[0][2:].strip()}")

    # Pull AC table
    print("\nAcceptance Criteria:")
    in_ac = False
    for line in doc.body.splitlines():
        if line.startswith("## 4. ") and "验收准则" in line:
            in_ac = True
            continue
        if in_ac and line.startswith("## "):
            break
        if in_ac and line.strip().startswith("| AC-"):
            print(f"  {line.strip()}")

    # Amendments
    am_dir = _amendments_dir(args.project, args.task_id)
    if am_dir.exists():
        files = sorted(am_dir.glob("*.md"))
        if files:
            print("\nAmendments:")
            for f in files:
                print(f"  - {f.name}")
    return 0


def cmd_lock(args: argparse.Namespace) -> int:
    path = _spec_path(args.project, args.task_id)
    doc = _load_spec(path)
    if doc.status not in {"drafting", "amending"}:
        print(f"spec_admin: cannot lock from status={doc.status}", file=sys.stderr)
        return 1
    doc.frontmatter["status"] = "locked"
    doc.frontmatter["last_amended_at"] = _now_iso()
    _dump_spec(doc)
    print(f"locked: {path}")
    print(f"  version: {doc.version}")
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    path = _spec_path(args.project, args.task_id)
    doc = _load_spec(path)
    if doc.status == "drafting":
        print("spec_admin: cannot close a drafting spec; lock then close", file=sys.stderr)
        return 1
    doc.frontmatter["status"] = "closed"
    doc.frontmatter["last_amended_at"] = _now_iso()
    _dump_spec(doc)
    print(f"closed: {path}")
    return 0


def cmd_amend(args: argparse.Namespace) -> int:
    path = _spec_path(args.project, args.task_id)
    doc = _load_spec(path)
    if doc.status not in {"locked", "amending"}:
        print(f"spec_admin: cannot amend from status={doc.status}", file=sys.stderr)
        return 1
    am_dir = _amendments_dir(args.project, args.task_id)
    am_dir.mkdir(exist_ok=True)
    existing = sorted(am_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    next_n = len(existing) + 1
    slug = _slugify(args.summary)
    target_ver = doc.version
    result_ver = doc.bump_version()
    amend_name = f"{next_n:04d}-{slug}.md"
    amend_path = am_dir / amend_name
    ts = _now_iso()
    body_lines = []
    if args.body_file:
        body_lines.append(Path(args.body_file).read_text(encoding="utf-8"))
    elif args.body:
        body_lines.append(args.body)
    body_text = "\n".join(body_lines) if body_lines else "<!-- 详细变更说明 -->\n"
    amend_payload = (
        "---\n"
        f"amend_id: {next_n:04d}\n"
        f"target_version: {target_ver}\n"
        f"result_version: {result_ver}\n"
        f"proposer: {args.proposer}\n"
        f"approved_by: {args.approved_by}\n"
        f"approved_at: {ts}\n"
        f"impact_mode: {args.impact_mode}\n"
        "---\n\n"
        f"# {next_n:04d}: {args.summary}\n\n"
        f"## 变更\n\n{body_text}\n"
    )
    amend_path.write_text(amend_payload, encoding="utf-8")

    # Update SPEC.md frontmatter + 变更历史 table
    doc.frontmatter["version"] = result_ver
    doc.frontmatter["last_amended_at"] = ts
    history_row = f"| {result_ver} | {ts} | {args.summary} | {args.proposer} |"
    if "## 8. 变更历史" in doc.body:
        doc.body = doc.body.rstrip() + "\n" + history_row + "\n"
    _dump_spec(doc)

    print(f"amended: {amend_path}")
    print(f"  version: {target_ver} → {result_ver}")
    print(f"  impact: {args.impact_mode}")
    return 0


def _parse_ac_table(body: str) -> list[dict[str, str]]:
    """Extract AC rows from the markdown table under 验收准则."""
    ac_rows: list[dict[str, str]] = []
    in_ac = False
    for line in body.splitlines():
        if line.startswith("## 4. ") and "验收准则" in line:
            in_ac = True
            continue
        if in_ac and line.startswith("## "):
            break
        if not in_ac:
            continue
        stripped = line.strip()
        if not stripped.startswith("| AC-"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 4:
            continue
        ac_rows.append({
            "id": cells[0],
            "criterion": cells[1],
            "verify": cells[2],
            "status": cells[3],
        })
    return ac_rows


def _run_assert(cmd: str, cwd: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout after 300s"
    except Exception as exc:  # noqa: BLE001
        return False, f"exception: {exc!r}"
    detail = (result.stdout + result.stderr).strip()
    return result.returncode == 0, detail


def cmd_verify(args: argparse.Namespace) -> int:
    path = _spec_path(args.project, args.task_id)
    doc = _load_spec(path)
    if doc.status == "drafting":
        print("spec_admin: cannot verify a drafting spec; lock first", file=sys.stderr)
        return 1
    ac_rows = _parse_ac_table(doc.body)
    if not ac_rows:
        print("spec_admin: no AC rows found in SPEC.md", file=sys.stderr)
        return 1

    cwd = Path(args.cwd).expanduser() if args.cwd else Path.cwd()
    spec_dir = _spec_dir(args.project, args.task_id)
    results: list[tuple[dict[str, str], str, str]] = []
    all_ok = True
    for row in ac_rows:
        verify = row["verify"]
        if verify.startswith("`assert:") or verify.startswith("assert:"):
            cmd = verify.strip("`").removeprefix("assert:").strip()
            ok, detail = _run_assert(cmd, cwd)
            status = "passed" if ok else "failed"
        elif "script:" in verify:
            script_ref = verify.split("script:", 1)[1].strip().strip("`")
            script_path = spec_dir / script_ref if not script_ref.startswith("/") else Path(script_ref)
            if not script_path.exists():
                ok, detail = False, f"script not found: {script_path}"
                status = "failed"
            else:
                ok, detail = _run_assert(f"bash {script_path}", cwd)
                status = "passed" if ok else "failed"
        elif "人工" in verify or "manual" in verify.lower():
            ok, detail = (row["status"].lower() == "passed"), "human-judged"
            status = "manual-" + ("passed" if ok else "pending")
        else:
            ok, detail = False, f"unknown verify type: {verify}"
            status = "unknown"
        if not ok:
            all_ok = False
        results.append((row, status, detail))

    print(f"spec verify: {path}")
    print(f"  status: {doc.status} version: {doc.version}")
    print(f"  AC results:")
    for row, status, detail in results:
        marker = "✓" if status.endswith("passed") else "✗"
        print(f"    {marker} {row['id']} {status}: {row['criterion'][:60]}")
        if status.endswith("failed") and detail:
            print(f"        detail: {detail[:200]}")

    return 0 if all_ok else 2


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClawSeat task SPEC.md lifecycle helper.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Create new SPEC.md from template")
    p_create.add_argument("--project", required=True)
    p_create.add_argument("--task-id", required=True)
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--force", action="store_true")
    p_create.set_defaults(func=cmd_create)

    p_show = sub.add_parser("show", help="Pretty-print spec summary")
    p_show.add_argument("--project", required=True)
    p_show.add_argument("--task-id", required=True)
    p_show.set_defaults(func=cmd_show)

    p_lock = sub.add_parser("lock", help="Lock spec for execution (drafting → locked)")
    p_lock.add_argument("--project", required=True)
    p_lock.add_argument("--task-id", required=True)
    p_lock.set_defaults(func=cmd_lock)

    p_close = sub.add_parser("close", help="Close spec after final acceptance")
    p_close.add_argument("--project", required=True)
    p_close.add_argument("--task-id", required=True)
    p_close.set_defaults(func=cmd_close)

    p_amend = sub.add_parser("amend", help="Add an amendment (locked specs only)")
    p_amend.add_argument("--project", required=True)
    p_amend.add_argument("--task-id", required=True)
    p_amend.add_argument("--summary", required=True, help="One-line change summary (used as title + slug)")
    p_amend.add_argument("--proposer", default="memory", help="Who proposed: memory/user/planner/etc")
    p_amend.add_argument("--approved-by", default="user", help="Who approved")
    p_amend.add_argument("--impact-mode", choices=["queue", "suspend", "redirect"], default="queue",
                         help="How in-flight specialists handle the amendment")
    body_group = p_amend.add_mutually_exclusive_group()
    body_group.add_argument("--body", help="Amendment body text inline")
    body_group.add_argument("--body-file", help="Read amendment body from this file")
    p_amend.set_defaults(func=cmd_amend)

    p_verify = sub.add_parser("verify", help="Run AC asserts/scripts and report pass/fail")
    p_verify.add_argument("--project", required=True)
    p_verify.add_argument("--task-id", required=True)
    p_verify.add_argument("--cwd", help="Working directory for assert commands (default: $PWD)")
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
