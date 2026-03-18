---
name: kaiwu-lessons
description: Diagnose errors using kaiwu's error knowledge base and DeepSeek
argument-hint: [error text or "last"]
---

Call the kaiwu_lessons MCP tool to diagnose an error.

**Always pass these parameters:**
- `error_text`: $ARGUMENTS — pass the full traceback/error message. If $ARGUMENTS is "last" or empty, use the most recent error from the conversation.
- `host_level`: "strong"
- `session_id`: Use the current session ID if available
- `is_looping`: Set to true if this same error has been seen before in this session

**Important:**
- Pass the COMPLETE traceback, not just the last line
- If `is_looping` is true, kaiwu will suggest alternative approaches — you MUST switch strategy
- The response includes: error fingerprint match, fuzzy match, and optionally DeepSeek diagnosis
