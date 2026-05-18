"""ClawSeat TUI surface — wizards + views over the v0.4 layered model.

Owned by the TUI engineer per docs/schemas/v0.4-layered-model.md §9.
Consumes: profile_validator (§7), machine_config (§9), project_binding (§9).
Produces: nothing outside of write_validated() calls — no direct TOML writes.
"""
