---
name: kaiwu-diagnosis
description: Use when an error, exception, traceback, or failure is detected during code execution. TRIGGER when Bash output contains "Error", "Exception", "Traceback", "FAIL", or non-zero exit codes. Guides error diagnosis through kaiwu's three-layer system.
version: 1.0.0
---

# kaiwu Diagnosis — Error Analysis

## Overview

kaiwu provides a three-layer error diagnosis system that prioritizes zero-token solutions before escalating to DeepSeek. Use this whenever an error occurs during task execution.

## Three-Layer Diagnosis

### Layer 1: Fingerprint Match (Zero Tokens)
Exact match against the local error knowledge base. Instant, free, most reliable.

### Layer 2: Fuzzy Match (Zero Tokens)
Pattern-based matching when exact fingerprint doesn't hit. Still free and fast.

### Layer 3: DeepSeek Analysis (Uses Tokens)
Full LLM analysis when local matching fails. Provides detailed root cause and fix strategy.

## How to Use

When you encounter an error:

1. **Capture the full error** — include the complete traceback, not just the last line
2. **Call kaiwu_lessons**:
   ```
   kaiwu_lessons(
     error_text=<full_traceback>,
     session_id=<id>,
     host_level="strong",
     is_looping=false
   )
   ```
3. **Apply the suggested fix**
4. If the same error recurs, call again with `is_looping=true` — kaiwu will suggest alternative approaches

## Loop Detection

If you see the same error pattern repeated:
- Set `is_looping=true` in the kaiwu_lessons call
- kaiwu will force a different approach
- You MUST follow the alternative strategy — do not retry the same fix

## Common Error Patterns

- **Import errors**: Check virtual environment and package installation
- **Encoding errors on Windows**: Ensure `encoding='utf-8'` on all file operations
- **MCP connection errors**: Run `/kaiwu-doctor` to diagnose
- **API rate limits**: Check quota with `/kaiwu-stats`
