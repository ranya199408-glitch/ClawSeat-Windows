# Gemini Planner Compatibility Notes

This note records the CC3 gate for running the planner seat on Gemini CLI in
the `clawseat-solo` template.

## Point 1: SKILL Frontmatter Loading

Status: mitigated.

Gemini workspace rendering does not rely on native `related_skills:`
frontmatter interpretation. `core/scripts/agent_admin_template.py` writes both
`AGENTS.md` and `GEMINI.md`, strips SKILL frontmatter, and embeds the planner
role SKILL body under `Role SKILL (canonical)`. The planner engineer config also
lists required SKILL.md paths explicitly, so the generated workspace shows the
resolved skill references even if Gemini ignores `related_skills`.

## Point 2: Claude-Specific Tool Dependencies

Status: verified.

`grep -n "TaskCreate\|Monitor\|TodoWrite" core/skills/planner/SKILL.md`
returns no hits. Planner workflow uses Markdown `workflow.md`, Python helpers,
`complete_handoff.py`, and `send-and-verify.sh`, which have bash/python
equivalents across tool seats.

## Point 3: CLAWSEAT_ROOT Relative Path Resolution

Status: verified.

`core/scripts/agent_admin_workspace.py::render_loaded_skills_lines` expands
`{CLAWSEAT_ROOT}` to the resolved repository root before rendering skill paths.
`core/scripts/agent_admin_template.py` then writes those expanded paths into
Gemini workspace documents.

## Point 4: Bash Subprocess Compatibility

Status: verified.

Planner handoff work is expressed through bash and Python commands:
`send-and-verify.sh`, `dispatch_task.py`, and `complete_handoff.py`. The
existing cross-tool protocol explicitly states that Gemini seats must call
`complete_handoff.py` themselves rather than relying on Claude Code Stop hooks,
so subprocess-style command execution is part of the expected Gemini workflow.
