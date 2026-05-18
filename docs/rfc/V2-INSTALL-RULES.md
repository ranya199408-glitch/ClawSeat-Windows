# V2 Install Rules

This document records hard ClawSeat install policy gates that protect already-deployed projects as ClawSeat itself evolves.

## Workspace Re-render Gate

Rendered workspace entry files (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`) carry first-line metadata:

```markdown
<!-- rendered_from_clawseat_sha=<sha> rendered_at=<iso-ts> renderer_version=v1 -->
```

When ClawSeat updates itself, `scripts/install.sh` checks deployed workspaces for stale `rendered_from_clawseat_sha` values. If stale workspaces are found, the installer prompts the operator to run:

```bash
agent_admin engineer regenerate-workspace --project <project> --all-seats
```

The regenerate command is intentionally non-destructive:

- It does not rewrite `project.toml` or `session.toml`.
- It does not stop or start tmux sessions.
- It backs up existing workspace prompt files under `<workspace>/.backup-<ts>/`.
- It prompts before overwriting files with local changes; bulk re-render after an installer prompt may use `--yes`.

Memory startup performs the same stale check as a warning only. A stale workspace should never prevent a memory seat from starting.

## Official Documentation Gate

External SDK/API/CLI tasks require a memory-owned official-docs research record before builder implementation, unless project-memory explicitly records why the docs gate is skipped.

The memory KB record lives under:

```text
~/.agents/memory/projects/<project>/findings/
```

It must include:

- Official documentation URL from an authoritative source.
- Package name, version, and CLI binary path when applicable.
- Relevant API contracts: method signatures, key schemas, and error codes.
- Inference boundary: what is documented vs what memory inferred.

Planner dispatch must carry either:

```bash
--task-type external-integration --docs-consulted <kb-record-path>
```

or:

```bash
--task-type external-integration --docs-skip-reason <reason>
```

`dispatch_task.py` enforces this only for explicit `external-integration` tasks. Existing dispatches without that task type remain backward compatible.

Builder DELIVERY must include a non-empty `Docs Consulted` section. Reviewer and QA treat a missing section as `CHANGES_REQUESTED` for external integration work.

## Install Canonicality

To create a new live project, the only canonical entry point is:

```bash
bash ~/ClawSeat/scripts/install.sh --project <name>
```

`agent_admin project create` is a building block for `install.sh` internals, not the user-facing command for live project creation. Calling it directly bypasses workspace rendering, profile generation, secret seeding, and skills installation.

`agent_admin project create` remains acceptable for:

- Unit tests and CI fixtures.
- Programmatic setup where the caller explicitly performs every missing install step.
- Low-level development of `agent_admin` itself.

`install.sh` is required for:

- Any new live project requested by an operator.
- Any project expected to have rendered seat workspaces, profiles, secrets, skills, and startup handoff files.

## RCA

This gate was added after the cartooner-memory durable handoff `cartooner-official-docs-memory-policy__cartooner-memory__install-memory.json`, which identified that official documentation research for external SDK/API/CLI work belongs to project-memory and must be referenced by planner dispatch and builder delivery evidence.
