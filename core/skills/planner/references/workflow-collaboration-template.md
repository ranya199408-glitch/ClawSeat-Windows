# Workflow Collaboration Template

## Workflow Collaboration

I execute steps assigned to me in workflow.md. planner is the author.

On receiving send-and-verify notification:

1. Read `~/.agents/tasks/<project>/<task_id>/workflow.md`
2. Find step where `owner_role=<my-role>`, `status=pending`, and all prereqs are done
3. `agent_admin task update-status <task_id> <step> in_progress --project <p>`
4. Execute `skill_commands` listed in step
5. Write artifacts and `DELIVERY.md`
6. `agent_admin task update-status <task_id> <step> done --project <p>`
7. Notify `notify_on_done` roles via send-and-verify

Poll fallback: if no push arrives after idle time, run
`agent_admin task list-pending --project <p> --owner-role <my-role>` and claim
only a ready step assigned to your role.

On failure (command error or `iter > max_iterations`):

- Do NOT retry silently.
- Notify `notify_on_blocked` roles.
- Record stderr, command output, and other evidence under `artifacts/`.
