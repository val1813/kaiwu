---
name: kaiwu-scene
description: Get scene-specific coding standards and best practices from kaiwu
argument-hint: [scene type]
---

Call the kaiwu_scene MCP tool to get coding standards for a specific scenario.

**Always pass these parameters:**
- `scene`: $ARGUMENTS (e.g., "api", "database", "testing", "frontend")
- `host_level`: "strong"
- `session_id`: Use the current session ID if available

**Scene types include:**
- API development
- Database operations
- Testing
- Frontend/UI
- DevOps/CI
- Security
- Performance optimization

If $ARGUMENTS is empty, ask the user what type of scene/scenario they need standards for.
