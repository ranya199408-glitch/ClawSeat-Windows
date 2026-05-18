# ClawSeat Install Interaction Mode

## Goal

Keep installation mostly automatic while preserving the frontstage rules that matter to the user.

## Agent Does Automatically

- inspect the current environment
- detect whether the requested project already has a live workspace or TUI seat and reuse it when present
- verify `CLAWSEAT_ROOT`
- run preflight
- materialize or update the starter profile
- run bootstrap for the target project
- verify the resulting console and workspace state

## Agent Must Surface Clearly

- whether the install target is `codex-bundle`, `claude-bundle`, or OpenClaw
- whether the project is new or existing
- whether there is already a live `builder`/`koder`-style TUI that should be resumed instead of recreated
- whether `koder` is only bootstrapped or actually live in frontstage
- whether the next blocker is ClawSeat config, first-launch onboarding, or host terminal capability

## Agent Must Ask Before

- launching any non-frontstage seat
- rebinding an existing seat to a different tool, auth mode, or provider
- entering or rotating API key / secret material, or changing provider-specific
  base URL / endpoint settings for an existing seat
- taking a recovery path that would discard a prior Claude session instead of resuming it

Exception:

- `/cs` already counts as approval to create or resume the canonical `install` project and start `planner`

## Manual User Steps

- Claude OAuth login or `claude --auth`
- workspace trust prompts
- permission bypass prompts
- rerunning the next tmux/seat command in a real terminal if the current host cannot open PTYs

## Reporting Style

- summarize each stage as `preflight`, `bootstrap`, `frontstage start`, or `manual onboarding`
- do not say "installation failed" when the system is waiting on a user TUI step
- do not say "ClawSeat is broken" when the real problem is tmux or PTY capability in the host environment
