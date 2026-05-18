# Workflows

This directory contains workflow definition files created by `cs-workflow` design mode.

Each file follows the format defined in `core/skills/cs-workflow/SKILL.md`.

## Naming convention

`<workflow_name>.md` — workflow definition  
`<workflow_name>-design_log.md` — design decision log

## Usage

**Design a new workflow** (via cs-workflow design mode):
```
Dispatch planner with cs-workflow skill, mode=design,
user_brief=<brief>, workflow_name=<name>
```

**Execute an existing workflow** (via cs-workflow execute mode):
```
Dispatch planner with cs-workflow skill, mode=execute,
workflow_name=<name>, project_params={brief_path: ..., output_dir: ...}
```
