# Builder pickup verification

Use this when a builder dispatch receipt arrives with branch/worktree locks.

1. Load the newest dispatch receipt for the task and source.
2. Read `expected_branch` and `expected_worktree_path`.
3. If both fields are missing, follow the legacy pickup path and continue.
4. If `expected_worktree_path` exists, verify the isolated worktree is present, clean, and on `expected_branch`; if it is missing or on the wrong branch, stop and re-home before editing.
5. If `expected_branch` exists but the current branch does not match, do not write code from that checkout; report the mismatch and wait for a fresh worktree or an explicit bypass.
6. Before the first DELIVERY write, add a `pickup_verified:` line that records the task id, branch, worktree path, and dispatch receipt path used for the pickup decision.
