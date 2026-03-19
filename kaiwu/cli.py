"""kaiwu CLI — 命令行管理工具

核心命令：
  kaiwu serve         启动 MCP Server
  kaiwu launch        验证 MCP 连接后启动 Claude Code（推荐）
  kaiwu doctor        诊断 MCP 连接状态（--fix 自动修复）
  kaiwu config        交互式配置向导
  kaiwu install --plugin  安装为 Claude Code Plugin（推荐）
  kaiwu install --mcp     注册 MCP Server（通用，兼容多平台）
  kaiwu install --mcp --claude-code  只注册 Claude Code
  kaiwu install --mcp --codex        只注册 Codex
  kaiwu install --mcp --cursor       只注册 Cursor
  kaiwu uninstall     卸载（全部或按平台）
  kaiwu stats         查看经验库/错误库统计

账号命令：
  kaiwu register      注册云端账号
  kaiwu login         登录
  kaiwu logout        登出
  kaiwu verify-email  验证邮箱
  kaiwu forgot-password  发送密码重置码
  kaiwu reset-password   重置密码

云端同步：
  kaiwu sync          同步云端库
  kaiwu contribute    上传经验到社区

"""

import json
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from kaiwu.config import get_config, KAIWU_HOME, CONFIG_PATH

console = Console()

# ── 版本常量 ──
CURRENT_VERSION = "0.2.0"
GITHUB_REPO = "val1813/kaiwu"
UPDATE_CHECK_CACHE = KAIWU_HOME / ".update_check.json"
UPDATE_CHECK_INTERVAL = 86400  # 24 小时


def _check_update_quiet() -> str | None:
    """后台检查 GitHub 最新版本，返回提示字符串或 None

    - 24h 内只查一次（缓存在 ~/.kaiwu/.update_check.json）
    - 网络失败静默返回 None，绝不阻塞
    """
    try:
        # 检查缓存
        if UPDATE_CHECK_CACHE.exists():
            cache = json.loads(UPDATE_CHECK_CACHE.read_text(encoding="utf-8"))
            if time.time() - cache.get("checked_at", 0) < UPDATE_CHECK_INTERVAL:
                latest = cache.get("latest_version", "")
                if latest and latest != CURRENT_VERSION and latest > CURRENT_VERSION:
                    return (
                        f"[yellow]有新版本可用: v{latest}（当前 v{CURRENT_VERSION}）[/yellow]\n"
                        f"[dim]升级: pip install --upgrade git+https://github.com/{GITHUB_REPO}.git[/dim]"
                    )
                return None

        # 请求 GitHub API（超时 3s）
        import urllib.request
        import urllib.error

        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tag = data.get("tag_name", "").lstrip("vV")
        if not tag:
            return None

        # 写缓存
        UPDATE_CHECK_CACHE.parent.mkdir(parents=True, exist_ok=True)
        UPDATE_CHECK_CACHE.write_text(
            json.dumps({"latest_version": tag, "checked_at": time.time()}, ensure_ascii=False),
            encoding="utf-8",
        )

        if tag != CURRENT_VERSION and tag > CURRENT_VERSION:
            return (
                f"[yellow]有新版本可用: v{tag}（当前 v{CURRENT_VERSION}）[/yellow]\n"
                f"[dim]升级: pip install --upgrade git+https://github.com/{GITHUB_REPO}.git[/dim]"
            )
    except Exception:
        pass  # 网络不通、API 限流、解析失败都静默
    return None


@click.group()
@click.version_option(version=CURRENT_VERSION, prog_name="cl-kaiwu")
def main():
    """开物 — AI Coding 增强引擎"""
    pass


@main.command()
def serve():
    """启动 MCP Server"""
    from kaiwu.server import main as serve_main
    serve_main()


@main.command()
def stats():
    """查看经验库/错误库/用量统计"""
    from kaiwu.storage.error_kb import ErrorKB
    from kaiwu.storage.experience import ExperienceStore
    from kaiwu.quota import get_usage_info

    console.print("\n[bold cyan]开物 cl-kaiwu 统计[/bold cyan]\n")

    # 用量
    usage = get_usage_info()
    table = Table(title="用量信息")
    table.add_column("项目", style="bold")
    table.add_column("值")
    table.add_row("当前计划", usage["plan"])
    table.add_row("今日调用", f"{usage['calls_today']}/{usage['limit']}")
    table.add_row("API Key", "已配置" if usage["has_api_key"] else "未配置")
    console.print(table)

    # 错误库
    kb = ErrorKB()
    kb_stats = kb.get_stats()
    table2 = Table(title="错误知识库")
    table2.add_column("项目", style="bold")
    table2.add_column("值")
    table2.add_row("总条目", str(kb_stats["total"]))
    table2.add_row("已解决", str(kb_stats["solved"]))
    table2.add_row("未解决", str(kb_stats["unsolved"]))
    console.print(table2)

    # 经验库
    exp = ExperienceStore()
    exp_stats = exp.get_stats()
    table3 = Table(title="经验库")
    table3.add_column("项目", style="bold")
    table3.add_column("值")
    table3.add_row("总条目", str(exp_stats["total"]))
    table3.add_row("成功经验", str(exp_stats["success"]))
    table3.add_row("失败教训", str(exp_stats["fail"]))
    if exp_stats["type_distribution"]:
        top_types = sorted(
            exp_stats["type_distribution"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]
        table3.add_row("热门类型", ", ".join(f"{t}({c})" for t, c in top_types))
    console.print(table3)


@main.group(invoke_without_command=True)
@click.pass_context
def session(ctx):
    """管理任务会话（无子命令时列出最近会话）"""
    if ctx.invoked_subcommand is None:
        ctx.invoke(session_list)


@session.command("list")
@click.option("--limit", default=10, help="显示数量")
def session_list(limit):
    """列出最近的 session"""
    from kaiwu.session import SessionManager
    from datetime import datetime

    sm = SessionManager()
    sessions = sm.list_sessions(limit=limit)

    if not sessions:
        console.print("[dim]暂无会话记录[/dim]")
        return

    table = Table(title="任务会话")
    table.add_column("Session ID", style="cyan")
    table.add_column("任务目标", max_width=40)
    table.add_column("轮数", justify="right")
    table.add_column("状态", justify="center")
    table.add_column("创建时间")

    for s in sessions:
        created = datetime.fromtimestamp(s["created_at"]).strftime("%m-%d %H:%M") if s["created_at"] else "-"
        status_style = {
            "active": "[green]active[/green]",
            "completed": "[dim]completed[/dim]",
            "failed": "[red]failed[/red]",
        }.get(s["status"], s["status"])
        table.add_row(
            s["session_id"],
            s["task"],
            str(s["turn_count"]),
            status_style,
            created,
        )

    console.print(table)


@session.command("show")
@click.argument("session_id")
def session_show(session_id):
    """展示 session 详情"""
    from kaiwu.session import SessionManager
    from datetime import datetime

    sm = SessionManager()
    data = sm.get(session_id)
    if not data:
        console.print(f"[red]会话不存在: {session_id}[/red]")
        return

    console.print(f"\n[bold cyan]会话: {session_id}[/bold cyan]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="bold", min_width=12)
    table.add_column("Value")

    table.add_row("任务目标", data.get("task", ""))
    table.add_row("状态", data.get("status", "unknown"))
    table.add_row("轮数", str(data.get("turn_count", 0)))

    created = data.get("created_at", 0)
    if created:
        table.add_row("创建时间", datetime.fromtimestamp(created).strftime("%Y-%m-%d %H:%M:%S"))
    updated = data.get("updated_at", 0)
    if updated:
        table.add_row("更新时间", datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M:%S"))

    console.print(table)

    # 锚点
    anchors = data.get("anchors", [])
    if anchors:
        console.print("\n[bold]决策锚点:[/bold]")
        for a in anchors:
            console.print(f"  [cyan]-[/cyan] {a}")

    # 进度
    progress = data.get("progress_summary", "")
    if progress:
        console.print(f"\n[bold]当前进度:[/bold] {progress}")

    # 待处理
    pending = data.get("pending_issues", [])
    if pending:
        console.print("\n[bold]待处理:[/bold]")
        for p in pending:
            console.print(f"  [yellow]-[/yellow] {p}")

    # 子任务
    subtasks = data.get("subtasks", [])
    if subtasks:
        console.print("\n[bold]子任务:[/bold]")
        for st in subtasks:
            status_icon = {"completed": "[green]OK[/green]", "failed": "[red]X[/red]"}.get(
                st.get("status", ""), "[dim]...[/dim]"
            )
            console.print(f"  {st.get('seq', '?')}. [{status_icon}] {st.get('title', '')}")

    # 最近操作
    recent = data.get("recent_turns", [])
    if recent:
        console.print("\n[bold]最近操作:[/bold]")
        for rt in recent[-5:]:
            result = f" -> {rt.get('result', '')[:60]}" if rt.get("result") else ""
            console.print(f"  [dim]turn {rt.get('turn', '?')}:[/dim] {rt.get('action', '')[:80]}{result}")


@session.command("delete")
@click.argument("session_id")
def session_delete(session_id):
    """删除指定 session"""
    from kaiwu.session import SessionManager

    sm = SessionManager()
    if sm.delete(session_id):
        console.print(f"[green]已删除会话: {session_id}[/green]")
    else:
        console.print(f"[red]会话不存在: {session_id}[/red]")


@session.command("clean")
@click.option("--days", default=7, help="清理 N 天前的旧会话")
def session_clean(days):
    """清理旧 session"""
    import time
    from kaiwu.config import SESSIONS_DIR

    now = time.time()
    threshold = days * 24 * 3600
    cleaned = 0

    for p in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            updated = data.get("updated_at", 0)
            if (now - updated) > threshold:
                p.unlink()
                cleaned += 1
        except Exception:
            continue

    console.print(f"[green]已清理 {cleaned} 个超过 {days} 天的会话[/green]")


@main.group(invoke_without_command=True)
@click.pass_context
def config(ctx):
    """查看/设置配置（无子命令时进入交互式向导）"""
    if ctx.invoked_subcommand is None:
        from kaiwu.wizard import run_wizard
        run_wizard()


@config.command("get")
@click.argument("key")
def config_get(key):
    """获取配置项"""
    cfg = get_config()
    value = cfg.get(key)
    if value is not None:
        console.print(f"{key} = {value}")
    else:
        console.print(f"[yellow]{key} 未设置[/yellow]")


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """设置配置项"""
    cfg = get_config()
    cfg.set(key, value)
    console.print(f"[green]已设置 {key} = {value}[/green]")
    console.print(f"配置文件: {CONFIG_PATH}")


@config.command("show")
def config_show():
    """显示所有配置"""
    if CONFIG_PATH.exists():
        content = CONFIG_PATH.read_text(encoding="utf-8")
        console.print(f"[dim]配置文件: {CONFIG_PATH}[/dim]\n")
        # 隐藏 API Key
        for line in content.split("\n"):
            if "api_key" in line and "sk-" in line:
                parts = line.split("=")
                if len(parts) == 2:
                    key_val = parts[1].strip().strip('"')
                    masked = key_val[:6] + "..." + key_val[-4:] if len(key_val) > 10 else "***"
                    console.print(f"{parts[0]}= \"{masked}\"")
                    continue
            console.print(line)
    else:
        console.print(f"[yellow]配置文件不存在: {CONFIG_PATH}[/yellow]")
        console.print("运行 [bold]kaiwu config set deepseek.api_key sk-xxx[/bold] 创建配置")


@main.command()
@click.option("--platform", type=click.Choice(["claude-code", "cursor", "vscode", "codex", "all"]),
              default="all", help="目标平台")
@click.option("--project-dir", type=click.Path(exists=True), default=".",
              help="项目目录（默认当前目录）")
@click.option("--plugin", is_flag=True, help="安装为 Claude Code Plugin（推荐 Claude Code 用户）")
@click.option("--mcp", is_flag=True, help="注册 MCP Server（通用，兼容 Claude Code/Cursor/Codex）")
@click.option("--claude-code", "flag_claude_code", is_flag=True, help="只注册 Claude Code MCP")
@click.option("--codex", "flag_codex", is_flag=True, help="只注册 Codex MCP")
@click.option("--cursor", "flag_cursor", is_flag=True, help="只注册 Cursor MCP")
def install(platform, project_dir, plugin, mcp, flag_claude_code, flag_codex, flag_cursor):
    """安装 kaiwu 到 AI 编程工具

    \b
    kaiwu install --plugin                Claude Code Plugin 安装（推荐）
    kaiwu install --mcp                   MCP Server 注册（全平台）
    kaiwu install --mcp --claude-code     只注册 Claude Code
    kaiwu install --mcp --codex           只注册 Codex
    kaiwu install --mcp --cursor          只注册 Cursor
    kaiwu install --mcp --claude-code --codex  组合注册
    kaiwu install                         传统安装（写 CLAUDE.md + 注册 MCP）
    """
    if plugin:
        _install_claude_code_plugin()
        return

    if mcp:
        # 收集目标平台
        targets = set()
        if flag_claude_code:
            targets.add("claude-code")
        if flag_codex:
            targets.add("codex")
        if flag_cursor:
            targets.add("cursor")
        # 无 flag 时注册全部（保持兼容）
        if not targets:
            targets = {"claude-code", "codex", "cursor"}
        _install_mcp_server(targets)
        return

    project = Path(project_dir).resolve()
    console.print(f"\n[bold cyan]安装 cl-kaiwu 到 {project}[/bold cyan]\n")

    targets = [platform] if platform != "all" else ["claude-code", "cursor", "vscode", "codex"]

    for target in targets:
        try:
            if target == "claude-code":
                _install_claude_code(project)
            elif target == "cursor":
                _install_cursor(project)
            elif target == "vscode":
                _install_vscode(project)
            elif target == "codex":
                _install_codex(project)
            console.print(f"  [green]OK[/green] {target}")
        except Exception as e:
            console.print(f"  [red]FAIL[/red] {target}: {e}")

    console.print(f"\n[bold]MCP Server 注册[/bold]")
    _register_mcp_server()
    console.print("\n[green]安装完成！[/green]")
    console.print("提示：确保已配置 API Key: kaiwu config")


def _install_claude_code(project: Path):
    """生成 CLAUDE.md（传统模式，推荐用 --plugin 替代）"""
    content = """# kaiwu 开物 — AI Coding 增强

> kaiwu MCP Server 运行时，优先调用它获取规划和诊断。

## 重要：传 host_level 参数
所有 kaiwu 工具都支持 host_level 参数，告知 kaiwu 你的能力等级：
- host_level="strong"：你是高级模型，kaiwu 只提供知识库+本地错误匹配+压缩
- host_level="medium"：中等模型，kaiwu 提供规划但不蒸馏
- host_level="weak"：需要全套 DeepSeek 规划+蒸馏+诊断

也可以传 host_model（你的模型名），kaiwu 会自动推断等级。

## 工作流
1. kaiwu_context(directory_tree, task, host_level="strong") → session_id
2. kaiwu_plan(task, context, session_id, host_level="strong") → 规划/知识库
3. 执行任务，遇错调 kaiwu_lessons(error_text, session_id, host_level="strong")
4. 完成后 kaiwu_record(task, session_id, success=True, host_level="strong")
5. 超15轮调 kaiwu_condense(mode="compress", session_id, history, host_level="strong")

## 要点
- host_level 每次调用都要传（或传 host_model 自动推断）
- kaiwu_lessons: error_text 传完整 Traceback
- is_looping=true 时必须换方案
- 传 project_name 让经验按项目隔离

## 质量规则
- 修改文件前先读取确认内容
- 局部修改失败时改用全量覆盖
- 中文 Windows: 文件操作指定 encoding='utf-8'
"""
    claude_md = project / "CLAUDE.md"
    # 如果已存在，追加而非覆盖
    if claude_md.exists():
        existing = claude_md.read_text(encoding="utf-8")
        if "kaiwu" not in existing.lower():
            claude_md.write_text(existing + "\n\n" + content, encoding="utf-8")
    else:
        claude_md.write_text(content, encoding="utf-8")


def _find_plugin_root() -> Path | None:
    """查找 kaiwu 插件根目录（含 .claude-plugin/plugin.json 的目录）

    查找顺序：
    1. __file__ 的 parent.parent（开发模式 pip install -e，或仓库直接运行）
    2. pip show 的 Editable project location
    3. site-packages 根目录（pip install 非 editable 模式，插件文件通过 force-include 打包）
    4. 当前工作目录
    """
    import subprocess as sp

    # 1. 直接从源码路径推断（开发模式）
    candidate = Path(__file__).parent.parent.resolve()
    if (candidate / ".claude-plugin" / "plugin.json").exists():
        return candidate

    # 2. 从 pip show 获取（处理 editable install）
    try:
        result = sp.run(
            [sys.executable, "-m", "pip", "show", "cl-kaiwu"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.split("\n"):
            if line.startswith("Editable project location:"):
                loc = Path(line.split(":", 1)[1].strip())
                if (loc / ".claude-plugin" / "plugin.json").exists():
                    return loc
    except Exception:
        pass

    # 3. site-packages 根目录（force-include 把插件文件装到了包安装位置的顶层）
    try:
        result = sp.run(
            [sys.executable, "-m", "pip", "show", "-f", "cl-kaiwu"],
            capture_output=True, text=True, timeout=10
        )
        location = None
        for line in result.stdout.split("\n"):
            if line.startswith("Location:"):
                location = Path(line.split(":", 1)[1].strip())
                break
        if location and (location / ".claude-plugin" / "plugin.json").exists():
            return location
    except Exception:
        pass

    # 4. 当前工作目录
    cwd = Path.cwd()
    if (cwd / ".claude-plugin" / "plugin.json").exists():
        return cwd

    return None


def _install_claude_code_plugin():
    """安装 kaiwu 为 Claude Code Plugin（注册为本地 marketplace）"""
    import subprocess as sp
    from datetime import datetime, timezone

    console.print("\n[bold cyan]安装 kaiwu 为 Claude Code Plugin[/bold cyan]\n")

    plugin_root = _find_plugin_root()
    if plugin_root is None:
        console.print("  [red]FAIL[/red] 未找到 kaiwu 插件根目录（需要含 .claude-plugin/plugin.json）")
        console.print()
        console.print("  可能原因：通过 pip install 安装时源码未包含插件文件")
        console.print("  解决方法：请在 kaiwu 仓库根目录下运行此命令：")
        console.print("    cd <kaiwu仓库路径>")
        console.print("    kaiwu install --plugin")
        return

    console.print(f"  [green]OK[/green] 插件根目录: {plugin_root}")

    # 1. 模板化 .mcp.json 中的 Python 路径
    mcp_json_path = plugin_root / ".mcp.json"
    python_path = sys.executable.replace("\\", "/")
    mcp_config = {
        "kaiwu": {
            "command": python_path,
            "args": ["-m", "kaiwu.server"],
            "cwd": "${CLAUDE_PLUGIN_ROOT}",
            "env": {
                "PYTHONIOENCODING": "utf-8"
            }
        }
    }
    mcp_json_path.write_text(
        json.dumps(mcp_config, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    console.print(f"  [green]OK[/green] .mcp.json 已更新 (python={python_path})")

    # 2. 创建 junction 到 marketplaces/ 目录
    marketplaces_dir = Path.home() / ".claude" / "plugins" / "marketplaces"
    target = marketplaces_dir / "kaiwu"
    marketplaces_dir.mkdir(parents=True, exist_ok=True)

    if target.exists() or target.is_symlink():
        try:
            if target.resolve() == plugin_root:
                console.print(f"  [green]OK[/green] Junction 已存在且正确: {target}")
            else:
                console.print(f"  [yellow]WARN[/yellow] Junction 存在但指向: {target.resolve()}")
                console.print("  删除后重新创建...")
                if target.is_dir():
                    sp.run(["cmd", "/c", "rmdir", str(target)],
                           capture_output=True, check=True)
                else:
                    target.unlink()
                sp.run(
                    ["cmd", "/c", "mklink", "/J", str(target), str(plugin_root)],
                    capture_output=True, check=True
                )
                console.print(f"  [green]OK[/green] Junction 已重建: {target} -> {plugin_root}")
        except Exception as e:
            console.print(f"  [red]FAIL[/red] Junction 处理失败: {e}")
            return
    else:
        try:
            sp.run(
                ["cmd", "/c", "mklink", "/J", str(target), str(plugin_root)],
                capture_output=True, check=True
            )
            console.print(f"  [green]OK[/green] Junction 已创建: {target} -> {plugin_root}")
        except Exception as e:
            console.print(f"  [red]FAIL[/red] 创建 Junction 失败: {e}")
            console.print(f"  可手动执行: mklink /J \"{target}\" \"{plugin_root}\"")
            return

    # 3. 注册到 known_marketplaces.json
    km_path = Path.home() / ".claude" / "plugins" / "known_marketplaces.json"
    try:
        if km_path.exists():
            km_data = json.loads(km_path.read_text(encoding="utf-8"))
        else:
            km_data = {}

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        km_data["kaiwu"] = {
            "source": {
                "source": "github",
                "repo": "val1813/kaiwu"
            },
            "installLocation": str(target).replace("/", "\\"),
            "lastUpdated": now_iso
        }
        km_path.write_text(
            json.dumps(km_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        console.print(f"  [green]OK[/green] 已注册到 known_marketplaces.json")
    except Exception as e:
        console.print(f"  [yellow]WARN[/yellow] marketplace 注册失败: {e}")
        console.print("  插件文件已就位，可能需要手动重启 Claude Code")

    # 4. 清理旧的 plugins/kaiwu junction（如果存在）
    old_target = Path.home() / ".claude" / "plugins" / "kaiwu"
    if old_target.exists() and old_target.is_dir():
        try:
            sp.run(["cmd", "/c", "rmdir", str(old_target)],
                   capture_output=True, check=False)
        except Exception:
            pass

    # 5. 在 settings.json 中启用插件（enabledPlugins）
    claude_settings = Path.home() / ".claude" / "settings.json"
    try:
        if claude_settings.exists():
            data = json.loads(claude_settings.read_text(encoding="utf-8"))
        else:
            data = {}

        enabled = data.get("enabledPlugins", {})
        enabled["kaiwu@kaiwu"] = True
        data["enabledPlugins"] = enabled
        claude_settings.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        console.print(f"  [green]OK[/green] 已启用插件 (enabledPlugins)")
    except Exception as e:
        console.print(f"  [yellow]WARN[/yellow] enabledPlugins 写入失败: {e}")
        console.print("  请手动在 settings.json 中添加: \"enabledPlugins\": {\"kaiwu@kaiwu\": true}")

    # 6. 检查旧 MCP 注册并提示
    if claude_settings.exists():
        try:
            data = json.loads(claude_settings.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", {})
            if "kaiwu" in servers:
                console.print()
                console.print("  [yellow]提示[/yellow] 检测到 settings.json 中有旧的 mcpServers.kaiwu 配置")
                console.print("  Plugin 模式下 MCP 服务器由插件内 .mcp.json 管理，")
                console.print("  建议移除 settings.json 中的 kaiwu MCP 配置以避免重复注册。")
                console.print(f"  配置文件: {claude_settings}")
        except Exception:
            pass

    console.print()
    console.print("[green]Plugin 安装完成！[/green]")
    console.print("[dim]重启 Claude Code 后生效。可用 /kaiwu-plan 等命令验证。[/dim]")


def _install_cursor(project: Path):
    """生成 .cursor/rules/ 文件"""
    rules_dir = project / ".cursor" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    content = """---
description: kaiwu 开物编码增强规则
globs: ["**/*.py", "**/*.js", "**/*.ts", "**/*.jsx", "**/*.tsx", "**/*.html", "**/*.css", "**/*.sh", "**/*.sql"]
---

# kaiwu 编码增强

## 核心规则
- 修改文件前先读取确认内容
- 局部修改失败时改用全量覆盖方式重写
- 中文 Windows: 所有文件操作指定 encoding='utf-8'
- 不要使用 emoji/特殊 Unicode 符号作为日志输出
- 异常捕获具体类型，禁止裸 except
- 所有网络请求设置 timeout

## 如果安装了 kaiwu MCP Server
- 新任务 → kaiwu_plan
- 遇到错误 → kaiwu_lessons
- 任务完成 → kaiwu_record
"""
    (rules_dir / "kaiwu.mdc").write_text(content, encoding="utf-8")


def _install_vscode(project: Path):
    """生成 .github/copilot-instructions.md"""
    gh_dir = project / ".github"
    gh_dir.mkdir(parents=True, exist_ok=True)

    content = """# Copilot Instructions (by kaiwu)

## 编码规则
- 修改文件前先读取确认内容
- 中文 Windows: encoding='utf-8' 必须显式指定
- 异常捕获具体类型，禁止裸 except
- 所有网络请求设置 timeout
- CSV 输出用 encoding='utf-8-sig'（Excel 兼容中文）

## 如果安装了 kaiwu MCP Server，优先使用以下工具：
- kaiwu_plan: 获取任务规划
- kaiwu_lessons: 错误诊断
- kaiwu_record: 记录经验
- kaiwu_scene: 获取场景规范
"""
    instructions_file = gh_dir / "copilot-instructions.md"
    if not instructions_file.exists():
        instructions_file.write_text(content, encoding="utf-8")


def _install_codex(project: Path):
    """生成 AGENTS.md"""
    content = """# Agents Instructions (by kaiwu)

## 编码规则
- 修改文件前先读取确认当前内容
- 局部修改失败时改用全量覆盖
- 中文 Windows: 所有 Python 文件操作指定 encoding='utf-8'
- 不要使用 emoji 作为日志输出符号
- 异常捕获具体类型，禁止裸 except
- 所有网络请求设置 timeout

## 如果安装了 kaiwu MCP Server
优先调用 kaiwu_plan / kaiwu_lessons / kaiwu_record / kaiwu_scene 工具。
"""
    agents_md = project / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(content, encoding="utf-8")


def _install_mcp_server(targets: set[str] | None = None):
    """注册 kaiwu MCP Server 到各平台（通用模式，兼容 Claude Code/Cursor/Codex）

    Args:
        targets: 目标平台集合，如 {"claude-code", "cursor", "codex"}。None 表示全部。
    """
    import shutil

    if targets is None:
        targets = {"claude-code", "codex", "cursor"}

    console.print("\n[bold cyan]注册 kaiwu MCP Server[/bold cyan]\n")

    python_path = sys.executable.replace("\\", "/")
    console.print(f"  Python: {python_path}")

    mcp_config = {
        "command": python_path,
        "args": ["-m", "kaiwu.server"],
        "env": {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1"
        }
    }

    platforms_done = []

    # Claude Code — MCP: ~/.claude.json, hooks: ~/.claude/settings.json
    if "claude-code" in targets:
        claude_mcp_file = Path.home() / ".claude.json"
        try:
            if claude_mcp_file.exists():
                data = json.loads(claude_mcp_file.read_text(encoding="utf-8"))
            else:
                data = {}
            data.setdefault("mcpServers", {})
            data["mcpServers"]["kaiwu"] = {
                "type": "stdio",
                **mcp_config,
            }
            claude_mcp_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            console.print(f"  [green]OK[/green] Claude Code MCP: {claude_mcp_file}")
        except Exception as e:
            console.print(f"  [red]FAIL[/red] Claude Code MCP: {e}")

        # SessionStart hook 注册到 ~/.claude/settings.json
        claude_settings = Path.home() / ".claude" / "settings.json"
        try:
            claude_settings.parent.mkdir(parents=True, exist_ok=True)
            if claude_settings.exists():
                data = json.loads(claude_settings.read_text(encoding="utf-8"))
            else:
                data = {}

            hook_cmd = f'{python_path} -m kaiwu.notify'
            kaiwu_hook = {
                "matcher": "*",
                "hooks": [{
                    "type": "command",
                    "command": hook_cmd,
                    "timeout": 5,
                }],
            }
            data.setdefault("hooks", {})
            data["hooks"].setdefault("SessionStart", [])
            data["hooks"]["SessionStart"] = [
                h for h in data["hooks"]["SessionStart"]
                if "kaiwu" not in h.get("hooks", [{}])[0].get("command", "")
            ]
            data["hooks"]["SessionStart"].append(kaiwu_hook)

            claude_settings.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            platforms_done.append("Claude Code")
            console.print(f"  [green]OK[/green] Claude Code hook: {claude_settings}")
        except Exception as e:
            console.print(f"  [red]FAIL[/red] Claude Code hook: {e}")

    # Cursor — ~/.cursor/mcp.json
    if "cursor" in targets:
        cursor_settings = Path.home() / ".cursor" / "mcp.json"
        try:
            cursor_settings.parent.mkdir(parents=True, exist_ok=True)
            if cursor_settings.exists():
                data = json.loads(cursor_settings.read_text(encoding="utf-8"))
            else:
                data = {}
            data.setdefault("mcpServers", {})
            data["mcpServers"]["kaiwu"] = mcp_config
            cursor_settings.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            platforms_done.append("Cursor")
            console.print(f"  [green]OK[/green] Cursor: {cursor_settings}")
        except Exception as e:
            console.print(f"  [red]FAIL[/red] Cursor: {e}")

    # Codex — codex mcp add
    if "codex" in targets:
        if shutil.which("codex"):
            try:
                import subprocess
                codex_bin = shutil.which("codex")
                subprocess.run(
                    [codex_bin, "mcp", "remove", "kaiwu"],
                    capture_output=True, timeout=10,
                )
                result = subprocess.run(
                    [
                        codex_bin, "mcp", "add", "kaiwu",
                        "--env", "PYTHONIOENCODING=utf-8",
                        "--env", "PYTHONUNBUFFERED=1",
                        "--", python_path, "-m", "kaiwu.server",
                    ],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    platforms_done.append("Codex")
                    console.print(f"  [green]OK[/green] Codex: codex mcp add kaiwu")
                else:
                    console.print(f"  [red]FAIL[/red] Codex: {result.stderr.strip()}")
            except Exception as e:
                console.print(f"  [red]FAIL[/red] Codex: {e}")
        else:
            console.print(f"  [yellow]SKIP[/yellow] Codex: codex 命令未找到")

    console.print()
    if platforms_done:
        console.print(f"[green]MCP Server 注册完成！[/green] ({', '.join(platforms_done)})")
    else:
        console.print("[yellow]未注册到任何平台[/yellow]")
    console.print("[dim]重启编程工具后生效。kaiwu doctor 可验证连接。[/dim]")
    console.print("[dim]确保已配置 API Key: kaiwu config[/dim]")


def _register_mcp_server():
    """注册 MCP Server 到各平台配置"""
    # Claude Code
    claude_settings = Path.home() / ".claude" / "settings.json"
    _add_mcp_to_settings(claude_settings, "claude-code")

    # Cursor
    cursor_settings = Path.home() / ".cursor" / "mcp.json"
    _add_mcp_to_settings(cursor_settings, "cursor")


def _add_mcp_to_settings(settings_path: Path, platform: str):
    """添加 kaiwu MCP Server 配置到设置文件"""
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    mcp_config = {
        "command": sys.executable,
        "args": ["-m", "kaiwu.server"],
    }

    try:
        if settings_path.exists():
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        else:
            data = {}

        if platform == "cursor":
            data.setdefault("mcpServers", {})
            data["mcpServers"]["kaiwu"] = mcp_config
        else:
            data.setdefault("mcpServers", {})
            data["mcpServers"]["kaiwu"] = mcp_config

        settings_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        console.print(f"  [green]OK[/green] MCP Server 已注册到 {settings_path}")
    except Exception as e:
        console.print(f"  [yellow]WARN[/yellow] MCP 注册失败 ({platform}): {e}")


@main.command()
@click.option("--claude-code", "flag_claude_code", is_flag=True, help="只卸载 Claude Code")
@click.option("--codex", "flag_codex", is_flag=True, help="只卸载 Codex")
@click.option("--cursor", "flag_cursor", is_flag=True, help="只卸载 Cursor")
def uninstall(flag_claude_code, flag_codex, flag_cursor):
    """卸载 kaiwu MCP 注册

    \b
    kaiwu uninstall                全部卸载
    kaiwu uninstall --claude-code  只卸载 Claude Code
    kaiwu uninstall --codex        只卸载 Codex
    kaiwu uninstall --cursor       只卸载 Cursor
    """
    import shutil

    # 收集目标平台
    targets = set()
    if flag_claude_code:
        targets.add("claude-code")
    if flag_codex:
        targets.add("codex")
    if flag_cursor:
        targets.add("cursor")
    # 无 flag 时全部卸载
    if not targets:
        targets = {"claude-code", "codex", "cursor"}

    console.print("\n[bold cyan]卸载 kaiwu MCP Server[/bold cyan]\n")
    platforms_done = []

    # Claude Code — 删 ~/.claude.json 中 mcpServers.kaiwu + ~/.claude/settings.json 中 hooks
    if "claude-code" in targets:
        # 1) 删 MCP 注册
        claude_mcp_file = Path.home() / ".claude.json"
        try:
            if claude_mcp_file.exists():
                data = json.loads(claude_mcp_file.read_text(encoding="utf-8"))
                servers = data.get("mcpServers", {})
                if "kaiwu" in servers:
                    del servers["kaiwu"]
                    claude_mcp_file.write_text(
                        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
                    console.print(f"  [green]OK[/green] 已删除 Claude Code MCP: {claude_mcp_file}")
                else:
                    console.print(f"  [dim]SKIP[/dim] Claude Code MCP 未注册")
            else:
                console.print(f"  [dim]SKIP[/dim] {claude_mcp_file} 不存在")
        except Exception as e:
            console.print(f"  [red]FAIL[/red] Claude Code MCP: {e}")

        # 2) 删 hooks
        claude_settings = Path.home() / ".claude" / "settings.json"
        try:
            if claude_settings.exists():
                data = json.loads(claude_settings.read_text(encoding="utf-8"))
                hooks = data.get("hooks", {})
                changed = False

                # 删 SessionStart 中的 kaiwu hook
                if "SessionStart" in hooks:
                    before = len(hooks["SessionStart"])
                    hooks["SessionStart"] = [
                        h for h in hooks["SessionStart"]
                        if "kaiwu" not in h.get("hooks", [{}])[0].get("command", "")
                    ]
                    if len(hooks["SessionStart"]) < before:
                        changed = True
                    if not hooks["SessionStart"]:
                        del hooks["SessionStart"]

                # 删 settings.json 中旧的 mcpServers.kaiwu（如果存在）
                servers = data.get("mcpServers", {})
                if "kaiwu" in servers:
                    del servers["kaiwu"]
                    changed = True

                if changed:
                    claude_settings.write_text(
                        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
                    console.print(f"  [green]OK[/green] 已清理 Claude Code hooks: {claude_settings}")
                else:
                    console.print(f"  [dim]SKIP[/dim] Claude Code hooks 无 kaiwu 配置")
        except Exception as e:
            console.print(f"  [red]FAIL[/red] Claude Code hooks: {e}")

        platforms_done.append("Claude Code")

    # Cursor — 删 ~/.cursor/mcp.json 中 mcpServers.kaiwu
    if "cursor" in targets:
        cursor_settings = Path.home() / ".cursor" / "mcp.json"
        try:
            if cursor_settings.exists():
                data = json.loads(cursor_settings.read_text(encoding="utf-8"))
                servers = data.get("mcpServers", {})
                if "kaiwu" in servers:
                    del servers["kaiwu"]
                    cursor_settings.write_text(
                        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
                    console.print(f"  [green]OK[/green] 已删除 Cursor MCP: {cursor_settings}")
                else:
                    console.print(f"  [dim]SKIP[/dim] Cursor MCP 未注册")
            else:
                console.print(f"  [dim]SKIP[/dim] {cursor_settings} 不存在")
        except Exception as e:
            console.print(f"  [red]FAIL[/red] Cursor: {e}")

        platforms_done.append("Cursor")

    # Codex — codex mcp remove kaiwu
    if "codex" in targets:
        codex_bin = shutil.which("codex")
        if codex_bin:
            try:
                import subprocess
                result = subprocess.run(
                    [codex_bin, "mcp", "remove", "kaiwu"],
                    capture_output=True, text=True, timeout=10,
                )
                output = (result.stdout + result.stderr).lower()
                if "not found" in output or "no mcp" in output:
                    console.print(f"  [dim]SKIP[/dim] Codex MCP 未注册")
                elif result.returncode == 0:
                    console.print(f"  [green]OK[/green] 已删除 Codex MCP")
                else:
                    console.print(f"  [yellow]WARN[/yellow] Codex: {result.stderr.strip()}")
            except Exception as e:
                console.print(f"  [red]FAIL[/red] Codex: {e}")
        else:
            console.print(f"  [dim]SKIP[/dim] codex 命令未找到")

        platforms_done.append("Codex")

    console.print()
    if platforms_done:
        console.print(f"[green]卸载完成！[/green] ({', '.join(platforms_done)})")
    else:
        console.print("[yellow]未卸载任何平台[/yellow]")
    console.print("[dim]重启编程工具后生效。[/dim]")


@main.command()
@click.option("--on", "action", flag_value="on", help="启用 kaiwu")
@click.option("--off", "action", flag_value="off", help="禁用 kaiwu")
def toggle(action):
    """一键开关 kaiwu（在各平台 MCP 配置中启用/禁用）

    \b
    kaiwu toggle        自动切换(开/关)
    kaiwu toggle --on   强制启用
    kaiwu toggle --off  强制禁用
    """
    # 收集所有已注册的平台配置文件
    settings_files = [
        ("Claude Code", Path.home() / ".claude" / "settings.json"),
        ("Cursor", Path.home() / ".cursor" / "mcp.json"),
    ]

    found = []
    for name, path in settings_files:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", {})
            if "kaiwu" not in servers:
                continue
            found.append((name, path, data, servers["kaiwu"]))
        except Exception:
            continue

    if not found:
        console.print("[yellow]未发现已注册的 kaiwu MCP 配置[/yellow]")
        console.print("请先运行: kaiwu install")
        return

    # 判断当前状态（取第一个平台的状态作为基准）
    current_disabled = found[0][3].get("disabled", False)

    if action is None:
        # 自动切换
        new_disabled = not current_disabled
    else:
        new_disabled = (action == "off")

    # 应用到所有平台
    for name, path, data, server_cfg in found:
        if new_disabled:
            data["mcpServers"]["kaiwu"]["disabled"] = True
        else:
            data["mcpServers"]["kaiwu"].pop("disabled", None)

        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    status = "[red]已禁用[/red]" if new_disabled else "[green]已启用[/green]"
    platforms = ", ".join(name for name, *_ in found)
    console.print(f"kaiwu {status} ({platforms})")

    if new_disabled:
        console.print("[dim]重新启用: kaiwu toggle --on[/dim]")
    else:
        console.print("[dim]重启编程工具后生效[/dim]")


@main.command()
@click.option("--fix", is_flag=True, help="自动修复发现的问题")
def doctor(fix):
    """诊断 kaiwu MCP Server 连接状态

    \b
    kaiwu doctor        检查所有组件
    kaiwu doctor --fix  检查并自动修复
    """
    import subprocess as sp
    import threading
    import time

    checks_passed = 0
    checks_failed = 0

    console.print("\n[bold cyan]kaiwu 连接诊断[/bold cyan]\n")

    # ── 1. Python 环境 ──
    console.print("[bold]1. Python 环境[/bold]")
    try:
        import kaiwu as _kw
        console.print(f"   [green]OK[/green] kaiwu 已安装: {_kw.__file__}")
        checks_passed += 1
    except ImportError:
        console.print("   [red]FAIL[/red] kaiwu 未安装")
        if fix:
            console.print("   [yellow]修复中...[/yellow]")
            sp.run([sys.executable, "-m", "pip", "install", "-e", "."], cwd=str(Path(__file__).parent.parent))
        checks_failed += 1

    try:
        import mcp  # noqa: F811
        pip_out = sp.run([sys.executable, "-m", "pip", "show", "mcp"],
                         capture_output=True, text=True)
        for line in pip_out.stdout.split("\n"):
            if line.startswith("Version:"):
                ver = line.split(":")[1].strip()
                console.print(f"   [green]OK[/green] mcp {ver}")
                checks_passed += 1
                break
    except ImportError:
        console.print("   [red]FAIL[/red] mcp 包未安装")
        if fix:
            sp.run([sys.executable, "-m", "pip", "install", "mcp[cli]>=1.0"])
        checks_failed += 1

    # ── 2. 配置文件 ──
    console.print("[bold]2. 平台注册[/bold]")

    platforms = [
        ("Claude Code", Path.home() / ".claude" / "settings.json"),
        ("Cursor", Path.home() / ".cursor" / "mcp.json"),
    ]

    any_registered = False
    for name, path in platforms:
        if not path.exists():
            console.print(f"   [dim]SKIP[/dim] {name}: 配置文件不存在")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", {})
            if "kaiwu" in servers:
                disabled = servers["kaiwu"].get("disabled", False)
                if disabled:
                    console.print(f"   [yellow]WARN[/yellow] {name}: kaiwu 已注册但被禁用")
                    if fix:
                        servers["kaiwu"].pop("disabled", None)
                        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                        console.print(f"   [green]已修复[/green] 已启用 kaiwu")
                else:
                    console.print(f"   [green]OK[/green] {name}: kaiwu 已注册")
                    any_registered = True
                    checks_passed += 1
            else:
                console.print(f"   [red]FAIL[/red] {name}: kaiwu 未注册")
                if fix:
                    _add_mcp_to_settings(path, name.lower().replace(" ", "-"))
                    console.print(f"   [green]已修复[/green] 已写入 MCP 配置")
                    any_registered = True
                checks_failed += 1
        except Exception as e:
            console.print(f"   [red]FAIL[/red] {name}: {e}")
            checks_failed += 1

    if not any_registered and not fix:
        console.print("   [yellow]提示: 运行 kaiwu install 或 kaiwu doctor --fix 注册[/yellow]")

    # ── 3. MCP 握手测试 ──
    console.print("[bold]3. MCP Server 握手[/bold]")
    try:
        import os
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        proc = sp.Popen(
            [sys.executable, "-m", "kaiwu.server"],
            stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE,
            env=env,
        )

        init_req = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "kaiwu-doctor", "version": "1.0"},
            },
        })
        proc.stdin.write((init_req + "\n").encode("utf-8"))
        proc.stdin.flush()

        stdout_line = [None]
        def _read():
            stdout_line[0] = proc.stdout.readline()
        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout=10)

        if stdout_line[0]:
            resp = json.loads(stdout_line[0])
            if "result" in resp and "serverInfo" in resp["result"]:
                info = resp["result"]["serverInfo"]
                console.print(f"   [green]OK[/green] initialize 成功: {info['name']} v{info['version']}")
                checks_passed += 1

                # 继续测试 tools/list
                notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
                proc.stdin.write((notif + "\n").encode("utf-8"))
                proc.stdin.flush()

                list_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                proc.stdin.write((list_req + "\n").encode("utf-8"))
                proc.stdin.flush()

                tools_line = [None]
                def _read2():
                    tools_line[0] = proc.stdout.readline()
                t2 = threading.Thread(target=_read2, daemon=True)
                t2.start()
                t2.join(timeout=5)

                if tools_line[0]:
                    tools_resp = json.loads(tools_line[0])
                    tools = tools_resp.get("result", {}).get("tools", [])
                    names = [t["name"] for t in tools]
                    console.print(f"   [green]OK[/green] {len(tools)} 个工具: {', '.join(names)}")
                    checks_passed += 1
                else:
                    console.print("   [yellow]WARN[/yellow] tools/list 超时")
                    checks_failed += 1
            else:
                console.print(f"   [red]FAIL[/red] 异常响应: {resp}")
                checks_failed += 1
        else:
            console.print("   [red]FAIL[/red] 无响应（10s 超时）")
            stderr = proc.stderr.read(2048).decode("utf-8", errors="replace")
            if stderr:
                console.print(f"   [dim]stderr: {stderr[:300]}[/dim]")
            checks_failed += 1

        proc.kill()

    except Exception as e:
        console.print(f"   [red]FAIL[/red] 握手异常: {e}")
        checks_failed += 1

    # ── 4. LLM 配置 ──
    console.print("[bold]4. LLM 配置[/bold]")
    try:
        cfg = get_config()
        if cfg.llm_api_key:
            masked = cfg.llm_api_key[:6] + "..." + cfg.llm_api_key[-4:] if len(cfg.llm_api_key) > 10 else "***"
            console.print(f"   [green]OK[/green] Provider: {cfg.active_provider_name}, Key: {masked}")
            checks_passed += 1
        else:
            console.print("   [yellow]WARN[/yellow] 未配置 API Key（部分功能受限）")
            console.print("   [dim]运行 kaiwu config 配置[/dim]")
    except Exception as e:
        console.print(f"   [yellow]WARN[/yellow] 配置读取失败: {e}")

    # ── 汇总 ──
    console.print()
    if checks_failed == 0:
        console.print(f"[bold green]诊断通过[/bold green] ({checks_passed} 项全部正常)")
        console.print("[dim]可以启动 Claude Code 使用 kaiwu 了[/dim]")
    else:
        console.print(f"[bold yellow]发现 {checks_failed} 个问题[/bold yellow] ({checks_passed} 项正常)")
        if not fix:
            console.print("[dim]运行 kaiwu doctor --fix 尝试自动修复[/dim]")

    # ── 版本更新检查 ──
    update_msg = _check_update_quiet()
    if update_msg:
        console.print()
        console.print(update_msg)
    console.print()


@main.command()
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
def launch(extra_args):
    """验证 kaiwu 后启动 Claude Code

    \b
    kaiwu launch              验证 + 启动 claude
    kaiwu launch -- --resume  传额外参数给 claude
    """
    import subprocess as sp
    import threading
    import time
    import os
    import shutil

    console.print("\n[bold cyan]kaiwu launch[/bold cyan] — 验证 MCP 后启动 Claude Code\n")

    # ── 检查 claude 命令是否存在 ──
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        console.print("[red]未找到 claude 命令，请先安装 Claude Code[/red]")
        console.print("[dim]npm install -g @anthropic-ai/claude-code[/dim]")
        return

    # ── 版本更新检查 ──
    update_msg = _check_update_quiet()
    if update_msg:
        console.print(update_msg)
        console.print()

    # ── 快速 MCP 握手验证 ──
    console.print("[dim]验证 kaiwu MCP Server...[/dim]")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = sp.Popen(
            [sys.executable, "-m", "kaiwu.server"],
            stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE,
            env=env,
        )

        init_req = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "kaiwu-launch", "version": "1.0"},
            },
        })
        proc.stdin.write((init_req + "\n").encode("utf-8"))
        proc.stdin.flush()

        stdout_line = [None]
        def _read():
            stdout_line[0] = proc.stdout.readline()
        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout=8)

        proc.kill()

        if stdout_line[0]:
            resp = json.loads(stdout_line[0])
            if "result" in resp:
                console.print("[green]OK[/green] kaiwu MCP Server 就绪\n")
            else:
                console.print("[red]FAIL[/red] MCP 握手异常，运行 kaiwu doctor 查看详情")
                return
        else:
            console.print("[red]FAIL[/red] MCP Server 无响应（8s 超时）")
            console.print("[dim]运行 kaiwu doctor 诊断具体问题[/dim]")
            return

    except Exception as e:
        console.print(f"[red]FAIL[/red] 验证失败: {e}")
        return

    # ── 检查 settings.json 中 kaiwu 是否注册 ──
    claude_settings = Path.home() / ".claude" / "settings.json"
    if claude_settings.exists():
        data = json.loads(claude_settings.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        if "kaiwu" not in servers:
            console.print("[yellow]kaiwu 未注册到 Claude Code，自动注册中...[/yellow]")
            _add_mcp_to_settings(claude_settings, "claude-code")
        elif servers["kaiwu"].get("disabled"):
            console.print("[yellow]kaiwu 已禁用，自动启用中...[/yellow]")
            servers["kaiwu"].pop("disabled", None)
            claude_settings.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        console.print("[yellow]Claude Code 配置不存在，自动创建...[/yellow]")
        _add_mcp_to_settings(claude_settings, "claude-code")

    # ── 启动 Claude Code ──
    console.print("[bold]启动 Claude Code...[/bold]\n")
    cmd = [claude_cmd] + list(extra_args)
    result = sp.run(cmd)
    sys.exit(result.returncode)


@main.command()
def contribute():
    """上传本地优质经验贡献社区"""
    from kaiwu.storage.sync import CloudSync, CloudSyncError
    from kaiwu.storage.experience import ExperienceStore

    client = CloudSync()
    if not client.is_logged_in:
        console.print("[yellow]请先登录: kaiwu login[/yellow]")
        return

    # 读取本地经验库，筛选成功的
    store = ExperienceStore()
    all_exps = [e for e in store._data.values() if e.success and e.fix_strategy]

    if not all_exps:
        console.print("[yellow]本地暂无可贡献的经验（需要先用 kaiwu 完成一些任务）[/yellow]")
        return

    console.print(f"本地共 {len(all_exps)} 条成功经验，开始上传...")
    uploaded = 0
    for exp in all_exps:
        try:
            ok = client.contribute({
                "task_type": exp.task_type,
                "task_description": exp.task_description[:500],
                "summary": exp.fix_strategy[:300],
                "key_steps": exp.key_steps[:10],
            })
            if ok:
                uploaded += 1
        except CloudSyncError:
            pass

    console.print(f"[green]已上传 {uploaded} 条经验到社区库，感谢贡献！[/green]")


@main.command()
@click.argument("username")
@click.argument("password")
@click.option("--email", "-e", default="", help="注册邮箱（用于密码重置）")
def register(username: str, password: str, email: str):
    """注册云端账号: kaiwu register <用户名> <密码> [-e 邮箱]"""
    from kaiwu.storage.sync import CloudSync, CloudSyncError
    try:
        client = CloudSync()
        result = client.register(username, password, email=email)
        console.print(f"[green]注册成功！[/green] 用户: {result['username']}")
        console.print(f"Token 已缓存，后续自动同步无需重复登录。")
        if email:
            console.print(f"[dim]验证码已发送到 {email}，请查收并执行：kaiwu verify-email {email} <验证码>[/dim]")
    except CloudSyncError as e:
        console.print(f"[red]注册失败: {e}[/red]")


@main.command()
@click.argument("username")
@click.argument("password")
def login(username: str, password: str):
    """登录云端: kaiwu login <用户名> <密码>"""
    from kaiwu.storage.sync import CloudSync, CloudSyncError
    try:
        client = CloudSync()
        result = client.login(username, password)
        console.print(f"[green]登录成功！[/green] 用户: {result['username']} (plan={result.get('plan')})")
    except CloudSyncError as e:
        console.print(f"[red]登录失败: {e}[/red]")


@main.command("verify-email")
@click.argument("email")
@click.argument("code")
def verify_email(email: str, code: str):
    """验证邮箱: kaiwu verify-email <邮箱> <验证码>"""
    from kaiwu.storage.sync import CloudSync, CloudSyncError
    try:
        client = CloudSync()
        client.verify_email(email, code)
        console.print(f"[green]邮箱验证成功！[/green]")
    except CloudSyncError as e:
        console.print(f"[red]验证失败: {e}[/red]")


@main.command("forgot-password")
@click.argument("email")
def forgot_password(email: str):
    """发送密码重置码: kaiwu forgot-password <邮箱>"""
    from kaiwu.storage.sync import CloudSync, CloudSyncError
    try:
        client = CloudSync()
        client.forgot_password(email)
        console.print(f"[green]重置码已发送到 {email}，请查收邮件。[/green]")
        console.print(f"[dim]然后执行：kaiwu reset-password {email} <验证码> <新密码>[/dim]")
    except CloudSyncError as e:
        console.print(f"[red]发送失败: {e}[/red]")


@main.command("reset-password")
@click.argument("email")
@click.argument("code")
@click.argument("new_password")
def reset_password(email: str, code: str, new_password: str):
    """重置密码: kaiwu reset-password <邮箱> <验证码> <新密码>"""
    from kaiwu.storage.sync import CloudSync, CloudSyncError
    try:
        client = CloudSync()
        client.reset_password(email, code, new_password)
        console.print(f"[green]密码已重置！请重新登录：kaiwu login <用户名> <新密码>[/green]")
    except CloudSyncError as e:
        console.print(f"[red]重置失败: {e}[/red]")


@main.command()
def sync():
    """从云端同步最新库数据"""
    from kaiwu.storage.sync import CloudSync, CloudSyncError
    client = CloudSync()
    if not client.is_logged_in:
        console.print("[yellow]请先登录: kaiwu login <用户名> <密码>[/yellow]")
        return
    try:
        result = client.sync_all()
        updated = result.get("updated", {})
        if updated:
            for lib_name in updated:
                console.print(f"  [green]+[/green] {lib_name} -> v{updated[lib_name]['version']}")
            console.print(f"[green]同步完成，已更新 {len(updated)} 个库[/green]")
        else:
            console.print("[dim]所有库已是最新版本[/dim]")
    except CloudSyncError as e:
        console.print(f"[red]同步失败: {e}[/red]")


@main.command()
def logout():
    """登出云端账号"""
    from kaiwu.storage.sync import CloudSync, CloudSyncError, TOKEN_PATH

    client = CloudSync()
    if not client.is_logged_in:
        console.print("[dim]当前未登录[/dim]")
        return

    # 通知服务端清除 token
    try:
        client.logout()
    except CloudSyncError:
        pass  # 服务端不可达也要清本地

    # 清除本地缓存
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
    console.print("[green]已登出[/green]")


if __name__ == "__main__":
    main()
