# Workflow Collaboration Protocol

All specialist seats follow this 7-step loop when executing workflow.md steps.

## 7-Step Loop

On receiving a `send-and-verify` notification:

1. Read `~/.agents/tasks/<project>/<task_id>/workflow.md`
2. Find the step where `owner_role=<my-role>`, `status=pending`, and all prereqs are done
3. `agent_admin task update-status <task_id> <step> in_progress --project <p>`
4. Execute the `skill_commands` listed in the step
5. Write artifacts and `DELIVERY.md`
6. `agent_admin task update-status <task_id> <step> done --project <p>`
7. Notify `notify_on_done` roles via send-and-verify

## Pull Fallback (recovery after restart/compact)

If no push notification arrives after idle time, poll for pending work:

```bash
agent_admin task list-pending --project <p> --owner-role <my-role>
```

Claim only steps assigned to your role where prereqs are satisfied.

## Failure Path

On command error or `iter > max_iterations`:

- Do NOT retry silently.
- Notify `notify_on_blocked` roles immediately.
- Record stderr, command output, and other evidence under `artifacts/`.
- Do not proceed to the next step while this step is blocked.
