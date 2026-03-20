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
        "🛠️ 开物(kaiwu)顾问在线！"
        "遇事不决调 kaiwu_plan，报错别慌调 kaiwu_lessons，完事记一笔 kaiwu_record。"
    )

    print(json.dumps({
        "continue": True,
        "suppressOutput": False,
        "systemMessage": msg,
    }))


if __name__ == "__main__":
    main()
