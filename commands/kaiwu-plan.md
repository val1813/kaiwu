---
name: kaiwu-plan
description: Get AI-powered task planning and knowledge base from kaiwu
argument-hint: [task description]
---

Call the kaiwu_plan MCP tool to get a structured plan for the given task.

**Always pass these parameters:**
- `task`: $ARGUMENTS (the task description from the user)
- `host_level`: "strong" (or "medium"/"weak" based on your capability)
- `session_id`: Use the current session ID if one exists from a prior kaiwu_context call
- `project_name`: The current project name for experience isolation

**Workflow:**
1. If no session exists yet, first call `kaiwu_context` with the directory tree and task to get a `session_id`
2. Then call `kaiwu_plan` with the task and session_id
3. Follow the returned plan steps

If $ARGUMENTS is empty, ask the user what task they want to plan.
