---
name: kaiwu-record
description: Record task completion experience to kaiwu's knowledge base
argument-hint: [success|fail] [summary]
---

Call the kaiwu_record MCP tool to record the outcome of a completed task.

**Always pass these parameters:**
- `task`: A summary of what was done
- `session_id`: The current session ID
- `success`: true if $1 is "success" or empty (default), false if $1 is "fail"
- `host_level`: "strong"
- `project_name`: The current project name

**When to use:**
- After completing a task successfully
- After a task fails (record the failure for future reference)
- The experience is stored locally and can be synced to the cloud

If $ARGUMENTS is empty, summarize the current task from conversation context and record as success.
