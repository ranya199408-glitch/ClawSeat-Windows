# Shells

This directory contains distribution shells only.

Shells may provide:

- platform-specific manifests such as `SKILL.md` or `AGENTS.md`
- minimal bootstrap / registry / entrypoint wiring
- adapter shims that bridge into `core/` and `adapters/`

Shells must not duplicate ClawSeat protocol logic. Core runtime logic stays in
`core/`, and harness implementation stays under `adapters/`.
