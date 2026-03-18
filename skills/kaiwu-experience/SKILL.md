---
name: kaiwu-experience
description: Use when a task is completed (successfully or failed), or when the conversation is about to end. TRIGGER when the user says "done", "finished", "that's it", or when a multi-step task concludes. Guides experience recording for future reuse.
version: 1.0.0
---

# kaiwu Experience — Knowledge Recording

## Overview

kaiwu builds a local knowledge base of coding experiences. Recording task outcomes helps future tasks benefit from past solutions. This skill reminds you to record experiences at the right time.

## When to Record

- After successfully completing a task
- After a task fails (failures are valuable lessons too)
- When the user indicates they're done with a task
- Before ending a long session

## How to Record

Call `kaiwu_record`:
```
kaiwu_record(
  task=<concise_task_summary>,
  session_id=<id>,
  success=true/false,
  host_level="strong",
  project_name=<project>
)
```

## What Makes a Good Record

- **Task summary**: Clear, concise description of what was done
- **Include context**: The problem type, technologies involved
- **Success/failure**: Honest assessment of the outcome
- **Project isolation**: Always pass `project_name` so experiences are grouped by project

## Experience Lifecycle

1. Recorded locally in `~/.kaiwu/experiences.json`
2. Queried automatically by `kaiwu_plan` and `kaiwu_lessons` for future tasks
3. Can be synced to cloud with `kaiwu sync`
4. Can be contributed to community with `kaiwu contribute`

## Prompting the User

If a task appears complete but no record has been made, gently remind:
> "Task complete. Would you like me to record this experience to kaiwu for future reference?"
