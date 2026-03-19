#!/usr/bin/env python3
"""SessionStart hook: notify Claude that kaiwu plugin is active.

Injects a system message at session start so Claude knows kaiwu tools
are available and how to use them. The user doesn't see this directly,
but Claude will be aware of kaiwu's presence.
"""
import json
import sys


def main():
    # 模型可见提示（systemMessage 注入到模型上下文）
    msg = (
        "[kaiwu plugin active] "
        "kaiwu AI coding enhancement is loaded. Available MCP tools: "
        "kaiwu_context, kaiwu_plan, kaiwu_lessons, kaiwu_record, kaiwu_condense, kaiwu_scene, kaiwu_profile. "
        "Workflow: new task -> kaiwu_plan, error -> kaiwu_lessons, done -> kaiwu_record. "
        "Always pass host_level=\"strong\" (or host_model for auto-detect). "
        "Slash commands: /kaiwu-plan, /kaiwu-lessons, /kaiwu-record, /kaiwu-scene, /kaiwu-doctor, /kaiwu-stats."
    )

    print(json.dumps({
        "continue": True,
        "suppressOutput": False,
        "systemMessage": msg,
    }))


if __name__ == "__main__":
    main()
