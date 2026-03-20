"""kaiwu SessionStart notification — 可通过 python -m kaiwu.notify 运行

输出 Claude Code hooks 协议格式的 JSON，告知模型 kaiwu MCP 工具已加载。
用于 MCP 模式安装（非 Plugin 模式）时的 SessionStart hook。
"""
import json
import sys
import os


def main():
    # 确保 stdout 输出 UTF-8（Windows 默认 GBK 会导致编码错误）
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    # 模型可见提示（systemMessage 注入到模型上下文）
    msg = (
        "🛠️ 开物(kaiwu)顾问在线！"
        "遇事不决调 kaiwu_plan，报错别慌调 kaiwu_lessons，完事记一笔 kaiwu_record。"
    )

    # stdout 输出纯 JSON（hooks 协议要求）
    print(json.dumps({
        "continue": True,
        "suppressOutput": False,
        "systemMessage": msg,
    }))


if __name__ == "__main__":
    main()
