#!/usr/bin/env python3
"""PostToolUse hook: detect error patterns in Bash output.

Reads tool result from stdin (JSON), checks for error patterns,
and outputs a JSON response with a systemMessage if errors are found.
"""
import json
import re
import sys


ERROR_PATTERNS = [
    r"Traceback \(most recent call last\)",
    r"Error:",
    r"Exception:",
    r"FAILED",
    r"error\[E",
    r"fatal:",
    r"panic:",
    r"FATAL",
    r"ModuleNotFoundError",
    r"ImportError",
    r"SyntaxError",
    r"TypeError",
    r"ValueError",
    r"KeyError",
    r"AttributeError",
    r"FileNotFoundError",
    r"PermissionError",
    r"ConnectionError",
    r"TimeoutError",
]

COMPILED = re.compile("|".join(ERROR_PATTERNS), re.IGNORECASE)

# Patterns to ignore (common false positives)
IGNORE_PATTERNS = [
    r"error_kb",
    r"error_text",
    r"ErrorKB",
    r"error_handler",
    r"on_error",
    r"error\.py",
    r"test.*error",
    r"# .*error",
    r"\"error\"",
    r"'error'",
]

IGNORE_COMPILED = re.compile("|".join(IGNORE_PATTERNS), re.IGNORECASE)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        # No input or invalid JSON — pass through
        print(json.dumps({"continue": True}))
        return

    # Get the tool output
    tool_output = data.get("tool_output", "") or ""
    if isinstance(tool_output, dict):
        tool_output = json.dumps(tool_output)

    # Check for error patterns
    matches = COMPILED.findall(tool_output)
    if not matches:
        print(json.dumps({"continue": True}))
        return

    # Filter out false positives
    real_errors = []
    for match in matches:
        # Check the line containing the match for ignore patterns
        for line in tool_output.split("\n"):
            if match.lower() in line.lower() and not IGNORE_COMPILED.search(line):
                real_errors.append(match)
                break

    if not real_errors:
        print(json.dumps({"continue": True}))
        return

    # Found real errors — suggest kaiwu_lessons
    error_types = list(set(real_errors))[:3]
    msg = (
        f"[kaiwu] Detected error pattern(s): {', '.join(error_types)}. "
        "Consider calling kaiwu_lessons with the full error text for diagnosis. "
        "Pass the complete traceback as error_text, and set is_looping=true "
        "if this error has been seen before in this session."
    )

    print(json.dumps({
        "continue": True,
        "suppressOutput": False,
        "systemMessage": msg,
    }))


if __name__ == "__main__":
    main()
