# Shared Tone

Use this reference when rendering user-facing text from clarify mode, report mode, goal drift recall, or reflection cards.

## Language

Chinese-first output is the default for Chinese-speaking projects. Mirror the user's language when the user writes clearly in another language.

## Terminology Tiers

Keep these terms in English because the user may need to find them in GitHub, the IDE, CI, or logs:

- PR
- commit
- branch
- merge
- push
- rebase
- diff
- CI
- hash
- SHA

Always translate these internal workflow terms:

- dispatch -> 派工
- dispatched -> 已派工
- seat -> 席位
- patrol -> 巡逻
- escalation -> 升级请求
- handoff -> 交接
- verdict -> 结论
- tests passed -> 测试通过
- tests failed -> 测试失败

Choose by context for these terms:

- skill: use `skill` inside ClawSeat tooling, otherwise `能力`
- agent: use `agent` for product concepts, otherwise `助手`
- session: use `session` for tmux/tooling, otherwise `会话`
- workspace: use `工作空间` unless the file path or tool UI says `workspace`

## Sentence Style

Prefer short sentences. Use Chinese punctuation in Chinese output. Keep Arabic numerals. Omit redundant subjects such as "我们" when the meaning is clear. Use at most one emoji anchor per card.
