#!/usr/bin/env python3
"""Stop hook: remind to record experience before session ends.

Outputs a systemMessage prompting kaiwu_record if a session is active.
"""
import json
import sys


def main():
    msg = (
        "[kaiwu] Before ending, consider recording this task's outcome with kaiwu_record. "
        "This builds the experience knowledge base for future tasks. "
        "Call kaiwu_record(task=<summary>, session_id=<id>, success=true/false, host_level=\"strong\")."
    )

    print(json.dumps({
        "continue": True,
        "suppressOutput": False,
        "systemMessage": msg,
    }))


if __name__ == "__main__":
    main()
