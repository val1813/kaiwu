"""交互式配置向导 — kaiwu config 无子命令时进入

菜单：
  1. 内嵌模型 API 设置（多 Provider 支持）
  2. Coding 软件 Key 设置（Claude Code / Cursor）
  3. 查看当前配置（Key 脱敏）
  0. 退出
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm

import click

from kaiwu.config import (
    get_config,
    reload_config,
    CONFIG_PATH,
    KAIWU_HOME,
    PROVIDER_DEFAULTS,
)

console = Console()

# ── Provider 预设 ──────────────────────────────────────────────────

_PROVIDER_CHOICES = {
    "1": ("deepseek", "DeepSeek"),
    "2": ("openai", "OpenAI"),
    "3": ("claude", "Claude (Anthropic)"),
    "4": ("custom", "自定义中转"),
}

_FORMAT_CHOICES = {
    "1": ("openai", "OpenAI 兼容 (/v1/chat/completions)"),
    "2": ("anthropic", "Anthropic 原生 (/v1/messages)"),
}


def _mask_key(key: str) -> str:
    """API Key 脱敏显示"""
    if not key or len(key) <= 10:
        return "***"
    return key[:6] + "..." + key[-4:]


def _detect_format_by_url(base_url: str) -> str:
    """根据 URL 关键词猜测 API 格式（快速预判）"""
    url_lower = base_url.lower()
    if "anthropic" in url_lower:
        return "anthropic"
    return "openai"


def _probe_api_format(api_key: str, base_url: str, model: str) -> tuple[str, str]:
    """发探测请求自动判断 API 格式

    策略：先试 Anthropic /v1/messages，再试 OpenAI /v1/chat/completions。
    哪个先返回有效响应（2xx 或认证类 4xx）就是哪个格式。
    纯网络错误或 404 说明该格式不通。

    Returns:
        (format, reason): format 为 "anthropic"/"openai"/"unknown"，reason 为人类可读原因
    """
    import httpx

    url = base_url.rstrip("/")

    # ── 探测 Anthropic 原生 ─────────────────────────────────
    try:
        resp = httpx.post(
            f"{url}/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            },
            timeout=10,
        )
        # 2xx = 成功; 401/403 = key 问题但端点存在; 400 = 参数不对但端点存在
        if resp.status_code in (200, 201, 400, 401, 403, 429):
            return "anthropic", f"/v1/messages 返回 {resp.status_code}"
    except Exception:
        pass

    # ── 探测 OpenAI 兼容 ───────────────────────────────────
    try:
        resp = httpx.post(
            f"{url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            },
            timeout=10,
        )
        if resp.status_code in (200, 201, 400, 401, 403, 429):
            return "openai", f"/v1/chat/completions 返回 {resp.status_code}"
    except Exception:
        pass

    return "unknown", "两个端点均无有效响应"


# ── 菜单 1: 内嵌模型 API 设置 ─────────────────────────────────────

def _setup_provider():
    """设置内嵌 LLM Provider"""
    console.print("\n[bold cyan]选择提供商：[/bold cyan]")
    for num, (_, display) in _PROVIDER_CHOICES.items():
        console.print(f"  {num}. {display}")
    console.print()

    choice = Prompt.ask("请选择", choices=list(_PROVIDER_CHOICES.keys()), default="1")
    provider_id, provider_name = _PROVIDER_CHOICES[choice]

    defaults = PROVIDER_DEFAULTS.get(provider_id, {})

    # API Key
    console.print()
    api_key = Prompt.ask("API Key", password=True)
    if not api_key.strip():
        console.print("[yellow]未输入 API Key，已取消[/yellow]")
        return

    # Base URL
    default_url = defaults.get("base_url", "")
    if provider_id == "custom":
        base_url = Prompt.ask("Base URL")
    else:
        base_url = Prompt.ask("Base URL", default=default_url)

    # Model
    default_model = defaults.get("model", "")
    if provider_id == "custom":
        model = Prompt.ask("模型名")
    else:
        model = Prompt.ask("模型名", default=default_model)

    # API Format — 先按 URL 关键词预判，再可选探测
    url_guess = _detect_format_by_url(base_url)
    console.print(f"\n[dim]URL 关键词预判格式: {url_guess}[/dim]")

    # 对自定义中转和非标准 URL，建议探测
    if provider_id == "custom" or url_guess == "openai":
        if Confirm.ask("是否自动探测 API 格式?（推荐，耗时 ~5s）", default=True):
            console.print("[dim]正在探测...[/dim]")
            probed, reason = _probe_api_format(api_key, base_url, model)
            if probed != "unknown":
                console.print(f"[green]探测结果: {probed}[/green] ({reason})")
                url_guess = probed
            else:
                console.print(f"[yellow]探测未确定: {reason}，使用 URL 预判[/yellow]")

    console.print("[bold]API 格式：[/bold]")
    for num, (_, desc) in _FORMAT_CHOICES.items():
        marker = " (检测)" if _FORMAT_CHOICES[num][0] == url_guess else ""
        console.print(f"  {num}. {desc}{marker}")

    default_fmt = "1" if url_guess == "openai" else "2"
    fmt_choice = Prompt.ask("请选择", choices=list(_FORMAT_CHOICES.keys()), default=default_fmt)
    api_format = _FORMAT_CHOICES[fmt_choice][0]

    # 可选: 测试连接
    console.print()
    if Confirm.ask("是否测试连接?", default=False):
        _test_connection(api_key, base_url, model, api_format)

    # 保存
    config = get_config()
    config.set(f"providers.{provider_id}.api_key", api_key)
    config.set(f"providers.{provider_id}.base_url", base_url)
    config.set(f"providers.{provider_id}.model", model)
    config.set(f"providers.{provider_id}.api_format", api_format)
    config.set("active_provider", provider_id)

    reload_config()

    console.print(f"\n[green]已保存并设为活跃提供商: {provider_name}[/green]")
    console.print(f"[dim]配置文件: {CONFIG_PATH}[/dim]")


def _test_connection(api_key: str, base_url: str, model: str, api_format: str):
    """测试 LLM 连接"""
    console.print("[dim]正在测试连接...[/dim]")
    try:
        if api_format == "anthropic":
            import httpx
            resp = httpx.post(
                f"{base_url.rstrip('/')}/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 10,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                console.print("[green]连接成功！[/green]")
            else:
                console.print(f"[yellow]HTTP {resp.status_code}: {resp.text[:200]}[/yellow]")
        else:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=10,
                timeout=15,
            )
            if response.choices:
                console.print("[green]连接成功！[/green]")
            else:
                console.print("[yellow]连接成功但无响应内容[/yellow]")
    except Exception as e:
        console.print(f"[red]连接失败: {e}[/red]")


# ── 菜单 2: Coding 软件 Key 设置 ──────────────────────────────────

def _setup_coding_software():
    """设置 Coding 软件的 API Key"""
    console.print("\n[bold cyan]选择 Coding 软件：[/bold cyan]")
    console.print("  1. Claude Code")
    console.print("  2. Cursor")
    console.print()

    choice = Prompt.ask("请选择", choices=["1", "2"], default="1")

    api_key = Prompt.ask("API Key", password=True)
    if not api_key.strip():
        console.print("[yellow]未输入 API Key，已取消[/yellow]")
        return

    base_url = Prompt.ask("Base URL (可选，留空跳过)", default="")

    config = get_config()

    if choice == "1":
        # Claude Code
        software_id = "claude_code"
        config.set(f"coding_software.{software_id}.api_key", api_key)
        if base_url:
            config.set(f"coding_software.{software_id}.base_url", base_url)

        # 写入 ~/.claude/settings.json 的 env 段
        _write_claude_code_env(api_key, base_url)
        console.print("[green]Claude Code API Key 已配置[/green]")

    else:
        # Cursor
        software_id = "cursor"
        config.set(f"coding_software.{software_id}.api_key", api_key)
        if base_url:
            config.set(f"coding_software.{software_id}.base_url", base_url)

        console.print("\n[green]Cursor API Key 已保存到 kaiwu 配置[/green]")
        console.print("[yellow]提示: Cursor 需要在其设置界面手动配置 API Key，或设置环境变量:[/yellow]")
        console.print(f"  OPENAI_API_KEY={_mask_key(api_key)}")
        if base_url:
            console.print(f"  OPENAI_BASE_URL={base_url}")

    reload_config()
    console.print(f"[dim]配置文件: {CONFIG_PATH}[/dim]")


def _write_claude_code_env(api_key: str, base_url: str = ""):
    """同步写入 Claude Code 所有配置位置

    参考 vibe.aiok.me/setup-claudecode.ps1 的做法，一次写全：
      1. ~/.claude/settings.json  — env 段（ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL + 关闭遥测）
      2. ~/.claude/config.json    — primaryApiKey（Claude Code 内部认证用）
      3. Windows 用户环境变量      — 持久化到注册表
    """
    claude_dir = Path.home() / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    wrote: list[str] = []

    # ── 1. ~/.claude/settings.json ─────────────────────────────
    settings_path = claude_dir / "settings.json"
    try:
        if settings_path.exists():
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        else:
            data = {}

        env = data.setdefault("env", {})
        # 中转站通常用 AUTH_TOKEN；同时设 API_KEY 兼容直连
        env["ANTHROPIC_AUTH_TOKEN"] = api_key
        env["ANTHROPIC_API_KEY"] = api_key
        if base_url:
            env["ANTHROPIC_BASE_URL"] = base_url
        elif "ANTHROPIC_BASE_URL" in env:
            del env["ANTHROPIC_BASE_URL"]

        # 中转用户建议关闭遥测，避免请求打到官方
        if base_url:
            env["DISABLE_TELEMETRY"] = "1"
            env["DISABLE_ERROR_REPORTING"] = "1"
            env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

        settings_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        wrote.append(str(settings_path))
    except Exception as e:
        console.print(f"  [red]写入 settings.json 失败: {e}[/red]")

    # ── 2. ~/.claude/config.json ───────────────────────────────
    config_json = claude_dir / "config.json"
    try:
        if config_json.exists():
            data2 = json.loads(config_json.read_text(encoding="utf-8"))
        else:
            data2 = {}

        data2["primaryApiKey"] = "claudecode"

        config_json.write_text(
            json.dumps(data2, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        wrote.append(str(config_json))
    except Exception as e:
        console.print(f"  [red]写入 config.json 失败: {e}[/red]")

    # ── 3. 环境变量持久化（区分平台） ──────────────────────────
    env_vars = {"ANTHROPIC_AUTH_TOKEN": api_key, "ANTHROPIC_API_KEY": api_key}
    if base_url:
        env_vars["ANTHROPIC_BASE_URL"] = base_url

    env_set: list[str] = []
    if sys.platform == "win32":
        # Windows: 通过 PowerShell 写用户级注册表
        for name, value in env_vars.items():
            try:
                _setenv_win(name, value)
                env_set.append(name)
            except Exception:
                pass
        if not env_set:
            console.print(f"  [yellow]写入环境变量失败[/yellow]")
            console.print(f'  [dim]可手动执行: setx ANTHROPIC_API_KEY "{_mask_key(api_key)}"[/dim]')
    else:
        # macOS / Linux: 写入 shell rc 文件
        try:
            rc_path = _write_shell_rc(env_vars)
            if rc_path:
                env_set = list(env_vars.keys())
        except Exception as e:
            console.print(f"  [yellow]写入 shell rc 失败: {e}[/yellow]")

    # 当前进程也设上
    for name, value in env_vars.items():
        os.environ[name] = value

    # ── 结果输出 ──────────────────────────────────────────────
    if wrote:
        console.print(f"  [green]已写入文件[/green] {', '.join(wrote)}")
    if env_set:
        console.print(f"  [green]已设置环境变量[/green] {', '.join(env_set)}")
        if sys.platform == "win32":
            console.print(f"  [dim]环境变量已持久化到 Windows 用户级，新窗口自动生效[/dim]")
        else:
            console.print(f"  [dim]请运行 source ~/.zshrc 或 source ~/.bashrc 使当前终端生效[/dim]")


def _setenv_win(name: str, value: str):
    """通过 PowerShell 设置 Windows 用户级环境变量（持久化到注册表）"""
    # 设置持久化环境变量
    ps_cmd = (
        f'[Environment]::SetEnvironmentVariable("{name}", "{value}", '
        f'[EnvironmentVariableTarget]::User)'
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True, timeout=10,
    )

    # 同时设置当前进程
    os.environ[name] = value


def _write_shell_rc(env_vars: dict[str, str]) -> str:
    """写入 macOS/Linux 的 shell rc 文件（~/.zshrc 或 ~/.bashrc）

    - 检测用户 shell 类型
    - 已有同名 export 行则 sed 替换，没有则追加
    - 返回写入的 rc 文件路径，失败返回空字符串
    """
    shell = os.environ.get("SHELL", "/bin/bash")
    shell_name = Path(shell).name

    if shell_name == "zsh":
        rc_path = Path.home() / ".zshrc"
    else:
        rc_path = Path.home() / ".bashrc"

    # 确保文件存在
    if not rc_path.exists():
        rc_path.touch()

    content = rc_path.read_text(encoding="utf-8")
    lines = content.split("\n")
    changed = False

    for name, value in env_vars.items():
        export_line = f'export {name}="{value}"'
        pattern = re.compile(rf'^export {re.escape(name)}=')

        # 查找已有行
        found = False
        for i, line in enumerate(lines):
            if pattern.match(line):
                if lines[i] != export_line:
                    lines[i] = export_line
                    changed = True
                found = True
                break

        if not found:
            # 追加
            if not lines or lines[-1] != "":
                lines.append("")
            if not any("Claude Code environment" in l for l in lines):
                lines.append("# Claude Code environment variables (added by kaiwu)")
            lines.append(export_line)
            changed = True

    if changed:
        rc_path.write_text("\n".join(lines), encoding="utf-8")
        console.print(f"  [green]已写入[/green] {rc_path}")

    return str(rc_path) if changed else ""


# ── 菜单 3: 查看当前配置 ──────────────────────────────────────────

def _show_config():
    """查看当前配置（Key 脱敏）"""
    config = get_config()

    console.print(f"\n[dim]配置文件: {CONFIG_PATH}[/dim]")

    if not CONFIG_PATH.exists():
        console.print("[yellow]配置文件不存在，尚未配置[/yellow]")
        return

    # 活跃提供商
    active = config.active_provider_name
    console.print(f"\n[bold]活跃提供商:[/bold] {active}")

    # Providers
    providers = config.get("providers") or {}
    if providers:
        table = Table(title="模型 Provider 列表")
        table.add_column("名称", style="bold")
        table.add_column("API Key")
        table.add_column("Base URL")
        table.add_column("模型")
        table.add_column("格式")
        table.add_column("状态")

        for name, prov in providers.items():
            if not isinstance(prov, dict):
                continue
            key = _mask_key(prov.get("api_key", ""))
            url = prov.get("base_url", "")
            model = prov.get("model", "")
            fmt = prov.get("api_format", "openai")
            status = "[green]活跃[/green]" if name == active else ""
            table.add_row(name, key, url, model, fmt, status)

        console.print(table)
    else:
        console.print("[yellow]未配置任何 Provider[/yellow]")

    # Coding Software
    coding = config.get("coding_software") or {}
    if coding:
        table2 = Table(title="Coding 软件配置")
        table2.add_column("软件", style="bold")
        table2.add_column("API Key")
        table2.add_column("Base URL")

        for name, sw in coding.items():
            if not isinstance(sw, dict):
                continue
            key = _mask_key(sw.get("api_key", ""))
            url = sw.get("base_url", "-")
            table2.add_row(name, key, url)

        console.print(table2)

    # License
    license_key = config.get("license.key")
    if license_key:
        console.print(f"\n[bold]License:[/bold] {_mask_key(license_key)}")


# ── 主菜单 ────────────────────────────────────────────────────────

def run_wizard():
    """运行交互式配置向导"""
    console.print(Panel.fit(
        "[bold cyan]开物 kaiwu — 配置向导[/bold cyan]",
        subtitle="kaiwu config",
    ))

    while True:
        console.print("\n[bold]请选择操作：[/bold]")
        console.print("  1. 内嵌模型 API 设置")
        console.print("  2. Coding 软件 Key 设置")
        console.print("  3. 查看当前配置")
        console.print("  0. 退出")
        console.print()

        choice = Prompt.ask("请选择", choices=["0", "1", "2", "3"], default="0")

        if choice == "0":
            console.print("[dim]再见！[/dim]")
            break
        elif choice == "1":
            _setup_provider()
        elif choice == "2":
            _setup_coding_software()
        elif choice == "3":
            _show_config()
