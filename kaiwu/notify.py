"""kaiwu SessionStart notification — 可通过 python -m kaiwu.notify 运行

输出 Claude Code hooks 协议格式的 JSON，告知模型 kaiwu MCP 工具已加载。
同时通过 stderr 向用户显示一行可见提示。
用于 MCP 模式安装（非 Plugin 模式）时的 SessionStart hook。
"""
import json
import sys


def main():
    # 用户可见提示（stderr 会显示在终端）
    print("⚡ kaiwu AI coding enhancement is active", file=sys.stderr)

    # 模型可见提示（systemMessage 注入到模型上下文）
    msg = (
        "[kaiwu active] "
        "kaiwu AI coding enhancement is loaded via MCP. Available tools: "
        "kaiwu_plan, kaiwu_lessons, kaiwu_record, kaiwu_context, kaiwu_condense, kaiwu_scene, kaiwu_profile. "
        "Workflow: new task → kaiwu_plan, error → kaiwu_lessons, done → kaiwu_record. "
        "Pass host_level=\"strong\" (or host_model for auto-detect) to each tool call."
    )

    print(json.dumps({
        "continue": True,
        "suppressOutput": False,
        "systemMessage": msg,
    }))


if __name__ == "__main__":
    main()
