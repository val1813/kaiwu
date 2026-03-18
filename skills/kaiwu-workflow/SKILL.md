---
name: kaiwu-workflow
description: Use when starting a new coding task, beginning a conversation, or when the user asks for help with planning. TRIGGER when the user describes a task to implement, fix, or build. Guides the kaiwu AI coding enhancement workflow.
version: 1.0.0
---

# kaiwu Workflow — AI Coding Enhancement

## Overview

kaiwu (开物) is an AI coding enhancement engine that provides planning, diagnosis, and experience learning. This skill guides the optimal workflow for using kaiwu MCP tools during coding tasks.

## Host Level

All kaiwu tools require a `host_level` parameter indicating the caller's capability:
- `host_level="strong"`: High-capability model — kaiwu provides knowledge base + local error matching + compression only
- `host_level="medium"`: Medium model — kaiwu provides planning without distillation
- `host_level="weak"`: Full DeepSeek planning + distillation + diagnosis

You can also pass `host_model` (your model name) and kaiwu will auto-detect the level.

## Standard Workflow

### 1. Initialize Context
At the start of a task, call `kaiwu_context`:
```
kaiwu_context(directory_tree=<tree>, task=<description>, host_level="strong")
```
This returns a `session_id` used in all subsequent calls.

### 2. Get Planning
Call `kaiwu_plan` to get task planning and relevant knowledge:
```
kaiwu_plan(task=<description>, context=<relevant_code>, session_id=<id>, host_level="strong")
```

### 3. Execute Task
Implement the plan. When errors occur, use `kaiwu_lessons` (see kaiwu-diagnosis skill).

### 4. Record Experience
After completion, call `kaiwu_record`:
```
kaiwu_record(task=<summary>, session_id=<id>, success=true/false, host_level="strong")
```

### 5. Compress Context (if needed)
After 15+ conversation turns, call `kaiwu_condense`:
```
kaiwu_condense(mode="compress", session_id=<id>, history=<recent_turns>, host_level="strong")
```

## Key Rules

- Pass `host_level` on EVERY kaiwu tool call
- Pass `project_name` to isolate experiences per project
- When `is_looping=true`, you MUST switch to a different approach
- Always pass the complete traceback to `kaiwu_lessons`, not just the last line
