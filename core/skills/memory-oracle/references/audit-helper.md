# Audit Helper Reference

This companion note holds the long-form checklist for `## 按需联网 (research / audit / 用户对齐场景)`.

## Use cases

- user 询问 SDK / API / library 当前文档或版本时，调用 docs fetch / WebSearch。
- brief 引用 enumerable facts（commit hash / library version）写不准时，联网 verify。
- operator 与 user 需求对齐（某 vendor 是否支持某 feature）时，联网调研。

## Privacy guard (必走)

1. 联网 query 前先调用 `core/skills/clawseat-privacy/SKILL.md` 做隐私检查。
2. query 字符串过滤 PII / secret / 内部 chat_id / project 内部 path。
3. 联网 result 写 KB 前同样过滤。
4. 不在联网 query 内含 user 真实姓名、token 片段、私有 repo 路径。

## Notes

- research lane 与用户对齐需要 vendor 文档和当前事实。
- privacy guard + 明确场景约束替代全局封禁。
- This helper is reference-only; the short form stays in `SKILL.md`.
