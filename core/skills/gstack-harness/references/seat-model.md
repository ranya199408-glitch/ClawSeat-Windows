# Seat Model

The harness runtime separates **stable seat identity** from **role semantics**.

## Required seat fields

- `seat_id`
- `role`
- `skills`
- `tool`
- `auth_mode`
- `provider`

## Supported runtime matrix

- `claude` + `oauth`: `anthropic`
- `claude` + `api`: `xcode-best`, `minimax`
- `codex` + `oauth`: `openai`
- `codex` + `api`: `xcode-best`
- `gemini` + `oauth`: `google`
- `gemini` + `api`: `google-api-key`

Unsupported combinations should be treated as invalid configuration, not as a
runtime surprise to discover later during launch.

## Provider endpoint rules

- `claude` + `api` + `xcode-best`
  - use `ANTHROPIC_BASE_URL=https://xcode.best`
  - this is the Claude-specific xcode endpoint
- `codex` + `api` + `xcode-best`
  - use `https://api.xcode.best/v1` in the Codex provider config
  - this is the GPT-5.4 / OpenAI-compatible xcode endpoint
- do not assume one `xcode-best` URL works for every CLI; the endpoint is
  tool-specific provider configuration

## Project-local runtime overrides

- seat identity stays stable across projects
- tool, auth mode, and provider may vary by project
- the preferred place to record those differences is the project profile via
  `seat_overrides`, not ad hoc post-bootstrap edits
- recommended heuristic:
  - large / multi-surface projects: `planner = claude`, `designer-1 = gemini`
  - pure frontend projects: `planner = gemini`, `designer-1` stays optional
    unless design work is active

## Dynamic Roster Fields

For dynamic-roster profiles, keep these fields distinct:

- `seats`
  - the canonical project roster
  - use this for role semantics, dispatch intent, and generated docs
- `materialized_seats`
  - the seats whose workspace/task scaffold should be pre-created at bootstrap
  - for starter profiles, this normally matches `seats`
- `runtime_seats`
  - the seats that should receive tmux session/runtime records
  - when `heartbeat_transport = "openclaw"`, this normally excludes `heartbeat_owner`
- `default_start_seats`
  - the seats frontstage should suggest or autostart first
  - this is a launch-order hint, not the roster definition
- `bootstrap_seats`
  - compatibility/frontstage-bootstrap field kept for older flows
  - do not treat this as the source of truth for “which seats get session records”

Recommended rule:

1. put the full team in `seats`
2. set `materialized_seats` to the seats that should already have workspace/task scaffolding after bootstrap
3. set `runtime_seats` to the seats that should have tmux session/runtime records
4. use `default_start_seats` for first-launch suggestions
5. keep `bootstrap_seats` only for backward-compatible frontstage/bootstrap behavior

## Configuration workflow

Frontstage must configure seats through the runtime tooling, not by editing
session files ad hoc.

- if the tool/runtime changes, use `agent-admin session switch-harness`
- if only auth mode or provider changes on the same tool, use
  `agent-admin engineer rebind`
- both paths re-render the seat workspace so the generated guide and
  `WORKSPACE_CONTRACT.toml` match the selected runtime

After the configuration change:

1. start or restart the seat
2. make the seat re-read its workspace guide
3. make the seat re-read `WORKSPACE_CONTRACT.toml`
4. stamp `scripts/ack_contract.py` when you need durable proof that the reread happened

Configuration changes that touch provider selection, auth mode, API keys, or
provider-specific base URLs/endpoints should be treated as a separate
configuration verification event, not as invisible setup noise.

Recommended split:

1. configuration entry
   - frontstage / planner records the selected tool/auth/provider and the
     operator supplies required secret material
2. configuration verification
   - planner uses reviewer/patrol lanes as needed to prove the seat can actually
     connect and behave correctly

`patrol-1` is the preferred verification seat when the change affects connectivity,
bridges, or provider reachability, but `patrol-1` should validate behavior without
becoming the seat that owns plaintext secrets long term.

This is how frontstage ensures the seat remembers its role, seat boundary, and
communication protocol after a runtime change.

If you batch-launch with a headless start path such as `--no-open-window` or
`--defer-window-refresh`, the seat is running but not yet visible in the
project tabs. Finish the batch with one project-window refresh before treating
the seat as operator-visible.

## Recovery workflow

When a Claude seat stops unexpectedly, do not jump straight to a fresh start.

Prefer this order:

1. check whether the original workspace still exists
2. check whether the original Claude runtime home still exists
3. check whether a prior Claude session record still exists
4. if all three exist, recover the seat on that same runtime first
5. only if recovery fails, do a fresh start and treat it as a new live session

For Claude recovery, keep these pieces aligned:

- workspace directory
- runtime `HOME`
- runtime `XDG_*` directories
- prior Claude session id, when available

Why this matters:

- a fresh Claude runtime can fall back into onboarding/login prompts even when
  OAuth credentials still exist
- preserving the original runtime home is often what keeps Claude's local seat
  state, trust prompts, and conversation/session memory intact

`ack_contract.py` is also the best future hook target:

- manual operator flow: run it after confirming the seat re-read the contract
- seat self-check flow: let the seat call it after re-reading
- hook flow: attach it to a post-start / post-reread automation once the
  runtime can reliably tell that the contract was actually re-read

## Authority flags

- `human_facing`
- `active_loop_owner`
- `dispatch_authority`
- `patrol_authority`
- `unblock_authority`
- `escalation_authority`
- `remind_active_loop_owner`
- `review_authority`
- `design_authority`

Legacy verification-seat aliases were removed on 2026-04-29. Writers and
readers must use `patrol` / `patrol_authority`.

## Canonical roles

- `frontstage-supervisor`
- `planner-dispatcher`
- `builder`
- `reviewer`
- `patrol`
- `designer`

## Operating rule

- frontstage-supervisor owns intake, patrol, approvals, confirmations, and
  unblock actions
- frontstage-supervisor also owns seat launch orchestration and operator
  window/tab composition for the project
- planner-dispatcher owns execution decisions and next-hop routing
- specialists do not become ad hoc frontstage agents
- when frontstage is about to launch a specialist/planner seat, it must first
  get user confirmation on the selected harness/runtime and model choice
- default to Simplified Chinese for human-readable task titles, objectives,
  reminders, closeout summaries, and user-facing handoff prose; preserve exact
  protocol keys, commands, file paths, API fields, and code identifiers as-is

## Legacy Cartooner Mapping

- `koder` -> `frontstage-supervisor`
- `engineer-b` -> `planner-dispatcher`
- `engineer-a` -> `builder`
- `engineer-c` -> `reviewer`
- `engineer-d` -> `patrol`
- `engineer-e` -> `designer`

This mapping is kept only for legacy projects that still run the historic
`engineer-*` roster, or for migration/debugging when you need to interpret old
runtime artifacts.

## Preferred Role-First Runtime IDs

- `koder` -> `frontstage-supervisor`
- `planner` -> `planner-dispatcher`
- `builder-1` -> `builder`
- `reviewer-1` -> `reviewer`
- `patrol-1` -> `patrol`
- `designer-1` -> `designer`

Prefer these ids for all new profiles, examples, and starter templates.
