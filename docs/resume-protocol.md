# ClawSeat resume protocol

This document is the contract for the DC session auto-resume flow.

## Active session marker

- The stop hook writes the last observed tool session id to
  `~/.agent-runtime/active/<seat>.session`.
- The launcher runtime reads the marker on spawn unless
  `CLAWSEAT_NO_AUTO_RESUME=1` is set.
- The file is seat-scoped, not tmux-session-scoped.

## Seat resume

- `agent_admin seat resume <seat>` resolves the seat through project.toml.
- `--fresh` skips auto-resume and starts a new session.
- Missing tmux session: spawn the launcher and let the runtime resume.
- Idle shell: send the resume command into the shell.
- Live harness: reject rather than double-launch.
- Repeating resume within 30 seconds is treated as a no-op.

## Project resume

- `agent_admin project resume <project>` walks the project seats and
  resumes each one.
- Failures are accumulated and reported at the end.
- `--fresh` is forwarded to every seat.

## Tool-specific commands

- Claude: `claude --resume <id>`
- Codex: `codex --resume <id>` or `codex --last`
- Gemini: `gemini --resume latest`

## Safety switches

- `CLAWSEAT_NO_AUTO_RESUME=1` disables launch-time auto-resume.
- Fresh session starts must continue to honor the explicit no-resume mode.
- The banner before attach is `Resuming session <id> from <timestamp>`.
- The launcher re-reads the seat marker on each spawn, so a new respawn always picks up the latest committed session id.
