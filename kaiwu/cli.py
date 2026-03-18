"""kaiwu CLI — 命令行管理工具

核心命令：
  kaiwu serve         启动 MCP Server
  kaiwu config        交互式配置向导
  kaiwu install       安装到各平台（Claude Code/Cursor/VS Code/Codex）
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

数据管理：
  kaiwu data show     查看本地数据
  kaiwu data delete   删除所有本地数据
  kaiwu data export   导出数据为 JSON
"""

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from kaiwu.config import get_config, KAIWU_HOME, CONFIG_PATH

console = Console()


@click.group()
@click.version_option(version="0.2.0", prog_name="cl-kaiwu")
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
def install(platform, project_dir):
    """安装 kaiwu 到 AI 编程工具"""
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
    """生成 CLAUDE.md"""
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


# ── 数据管理命令组 ────────────────────────────────────────────────

@main.group()
def data():
    """数据管理：查看、删除、导出本地数据"""
    pass


@data.command("show")
def data_show():
    """查看本地存储了哪些数据"""
    import json
    from kaiwu.config import KAIWU_HOME, EXPERIENCE_PATH, ERROR_KB_PATH, get_config

    console.print("\n[bold]开物本地数据概览[/bold]\n")

    # 经验库
    if EXPERIENCE_PATH.exists():
        try:
            raw = json.loads(EXPERIENCE_PATH.read_text(encoding="utf-8"))
            entries = raw.get("entries", [])
            if isinstance(entries, list):
                active = [e for e in entries if not e.get("deprecated", False)]
                console.print(f"  经验库：{len(active)} 条（已废弃 {len(entries)-len(active)} 条）")
            else:
                console.print(f"  经验库：{len(entries)} 条")
        except Exception:
            console.print("  经验库：读取失败")
    else:
        console.print("  经验库：空")

    # 错误库
    if ERROR_KB_PATH.exists():
        try:
            raw = json.loads(ERROR_KB_PATH.read_text(encoding="utf-8"))
            count = len(raw.get("entries", {}))
            console.print(f"  错误库：{count} 条")
        except Exception:
            console.print("  错误库：读取失败")
    else:
        console.print("  错误库：空")

    # 会话
    from kaiwu.config import SESSIONS_DIR
    if SESSIONS_DIR.exists():
        sessions = list(SESSIONS_DIR.glob("*.json"))
        console.print(f"  会话记录：{len(sessions)} 个")
    else:
        console.print("  会话记录：空")

    # 账号
    from kaiwu.storage.sync import TOKEN_PATH
    if TOKEN_PATH.exists():
        try:
            token_data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
            console.print(f"\n  账号：{token_data.get('username', '未知')} "
                          f"({token_data.get('plan', '未知')})")
        except Exception:
            pass

    # 隐私设置
    config = get_config()
    console.print(f"\n  隐私设置：")
    console.print(f"    匿名统计 (Level 1)：{'开启' if config.telemetry_enabled else '已关闭'}")
    console.print(f"    脱敏摘要 (Level 2)：{'开启' if config.data_sharing else '关闭（默认）'}")

    console.print(f"\n  [dim]数据路径：{KAIWU_HOME}[/dim]")
    console.print("  [dim]删除数据：kaiwu data delete[/dim]")
    console.print("  [dim]导出数据：kaiwu data export[/dim]\n")


@data.command("delete")
@click.option("--confirm", is_flag=True, help="跳过确认提示")
def data_delete(confirm: bool):
    """删除所有本地数据（不可恢复）"""
    from kaiwu.config import EXPERIENCE_PATH, ERROR_KB_PATH, SESSIONS_DIR

    if not confirm:
        click.confirm(
            "将删除所有本地经验库、错误库、会话数据。\n"
            "云端数据不受影响。确认删除？",
            abort=True
        )

    deleted = []
    for path in [EXPERIENCE_PATH, ERROR_KB_PATH]:
        if path.exists():
            path.unlink()
            deleted.append(path.name)

    # 清空会话目录
    if SESSIONS_DIR.exists():
        count = 0
        for f in SESSIONS_DIR.glob("*.json"):
            f.unlink()
            count += 1
        if count:
            deleted.append(f"sessions ({count} 个)")

    if deleted:
        console.print(f"[green]已删除：{', '.join(deleted)}[/green]")
    else:
        console.print("[dim]没有找到本地数据文件[/dim]")


@data.command("export")
@click.option("--output", "-o", default="kaiwu_data_export.json",
              help="导出文件路径")
def data_export(output: str):
    """导出所有本地数据为 JSON（你的数据你能带走）"""
    import json
    from kaiwu.config import EXPERIENCE_PATH, ERROR_KB_PATH

    export_data = {}
    for name, path in [
        ("experiences", EXPERIENCE_PATH),
        ("error_kb", ERROR_KB_PATH),
    ]:
        if path.exists():
            try:
                export_data[name] = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass

    output_path = Path(output)
    output_path.write_text(
        json.dumps(export_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    console.print(f"[green]数据已导出到：{output_path.absolute()}[/green]")


if __name__ == "__main__":
    main()
