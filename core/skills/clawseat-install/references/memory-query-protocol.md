# Seat → Memory Query Protocol

## Applies To

- All ClawSeat seats (koder, planner, builder-*, reviewer-*, patrol-*, designer-*)
- The ancestor Claude Code agent running any of the above
- Any script or hook that needs to consume an environment fact

## Knowledge Base Location

- Path: `~/.agents/memory/`
- Schema: structured facts (credentials, API keys, provider config, feishu group IDs, project decisions, install receipts)
- Permissions: `0600`; do not copy off the machine

## Query Tool

```sh
# Direct key lookup (fast, no reasoning)
python3 "$CLAWSEAT_ROOT/core/skills/memory-oracle/scripts/query_memory.py" \
  --key <path.to.fact>

# Search across entries
python3 "$CLAWSEAT_ROOT/core/skills/memory-oracle/scripts/query_memory.py" \
  --search <keyword>

# Reasoning query with profile context
python3 "$CLAWSEAT_ROOT/core/skills/memory-oracle/scripts/query_memory.py" \
  --ask "<question>" --profile <profile>
```

## Mandatory Query Rule

When you need any of the following, you MUST query memory BEFORE guessing, hardcoding, or asking the user:

- API keys (MiniMax / Anthropic / OpenAI / OpenRouter etc.)
- Provider / base URL / endpoint configuration
- Feishu group IDs / bridge configuration
- `~/.agents/.env.global` values
- File locations for project state, receipts, TODO queues

Guessing or hardcoding without a prior memory query is a contract violation.

## Missing-Key Escalation

If `query_memory.py` returns no result for a needed fact, immediately escalate via:

```sh
python3 "$CLAWSEAT_ROOT/core/skills/gstack-harness/scripts/notify_seat.py" \
  --profile <profile> --source <your-seat> --target memory \
  --task-id <short-slug> \
  --message "请调研 [具体问题] 并更新知识库"
```

Replace `[具体问题]` with the specific environment fact you need. Memory will scan and update its KB, then you can re-query.

Do NOT proceed with guessed values while waiting for memory. If the caller is time-sensitive, halt the chain and mark the task blocked on memory.

## Forbidden Patterns

- Hardcoding API keys inline, even "just for the smoke test"
- Reading env vars like `MINIMAX_API_KEY` without first confirming via memory that the key is correct / current
- Copying provider / base-URL strings from another project's profile without verifying via memory
- Prompting the user for a value that is already in memory

## Examples

- **New install on a fresh machine**: planner queries `credentials.keys.MINIMAX_API_KEY.value`; if present, use it; if absent, escalate to memory with "请调研 MiniMax API key 位置并更新知识库".
- **Dispatcher about to set provider**: query memory for `providers.<name>.status` before dispatching.
- **Feishu bridge test**: query memory for the bound group ID before calling `lark-cli`.

## Audit

- All seats should log memory queries (fact key + timestamp) in their task DELIVERY.md when the query influenced a decision.
- Memory should record all updates (source seat + correlated task_id) in its own DELIVERY.md.

## Version / Changelog

| Version | Date | Notes |
|---|---|---|
| v1 | 2026-04-19 | Initial protocol; memory seat elevated from optional to required |
