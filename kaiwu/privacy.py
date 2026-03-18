"""隐私保护模块 — 数据上传前的脱敏处理

所有上传到云端的数据必须经过本模块处理。
脱敏是强制的，不依赖用户配置。

数据分级：
- Level 0: 永不离开本地（task_description 原文、代码片段、文件路径中用户名等）
- Level 1: 匿名统计（task_type, error_category, platform, success 等）
- Level 2: 脱敏摘要（默认关闭，用户主动开启）
"""

import re
import sys
from loguru import logger


# ── 脱敏正则 ────────────────────────────────────────────────────

_RE_WIN_PATH = re.compile(r'[A-Za-z]:\\(?:[^\s,，。\n]+)')
_RE_UNIX_PATH = re.compile(r'(?:/[\w\-\.~]+){2,}')
_RE_REL_PATH = re.compile(r'\.\.?/[\w\-\./]+')
_RE_URL = re.compile(r'https?://[^\s，。,\n]+')
_RE_IP = re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b')
_RE_EMAIL = re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.]+\b')
_RE_PORT = re.compile(r':\d{4,5}\b')
_RE_QUOTED = re.compile(r'[\'\"「」『』]([^\'\"「」『』\n]{1,40})[\'\"「」『』]')
_RE_CAMEL = re.compile(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b')
_RE_LONG_SNAKE = re.compile(r'\b[a-z][a-z0-9]+(?:_[a-z0-9]+){2,}\b')


# ── 安全的错误类型名 ────────────────────────────────────────────

_SAFE_ERROR_CATEGORIES = {
    "UnicodeDecodeError", "UnicodeEncodeError", "UnicodeError",
    "ModuleNotFoundError", "ImportError",
    "FileNotFoundError", "PermissionError", "OSError",
    "JSONDecodeError", "ValueError", "TypeError", "KeyError",
    "AttributeError", "IndexError", "RuntimeError",
    "ConnectionRefusedError", "ConnectionError", "TimeoutError",
    "SyntaxError", "IndentationError",
    "RecursionError", "MemoryError", "OverflowError",
    "AssertionError", "NotImplementedError",
    "EOFError", "BrokenPipeError",
    # JS/Node
    "ENOENT", "EACCES", "EADDRINUSE", "ERR_MODULE_NOT_FOUND",
    "ReferenceError",
    # 网络
    "SSLError", "HTTPError", "URLError",
    # 数据库
    "OperationalError", "IntegrityError", "ProgrammingError",
}


def extract_error_category(error_text: str) -> str:
    """从完整错误信息里只提取错误类型名，绝不返回原文。

    "UnicodeDecodeError: 'gbk' codec can't decode..." → "UnicodeDecodeError"
    "npm ERR! ERESOLVE unable to resolve..." → "ERESOLVE"
    无法识别 → "UnknownError"
    """
    if not error_text:
        return ""

    text = error_text.strip()

    # Python 风格：XxxError: ...
    m = re.match(r'^([A-Za-z][A-Za-z0-9]*(?:Error|Exception|Warning|Fault))', text)
    if m and m.group(1) in _SAFE_ERROR_CATEGORIES:
        return m.group(1)

    # Node/npm 风格：ERR_XXX 或 EXXXXXX
    m = re.match(r'^(?:npm ERR!\s+)?([A-Z][A-Z0-9_]{2,})\b', text)
    if m:
        cat = m.group(1)
        if cat in _SAFE_ERROR_CATEGORIES:
            return cat
        if cat.startswith("E") and len(cat) <= 15:
            return cat

    # "xxx: message" 格式
    m = re.match(r'^([A-Za-z][A-Za-z0-9]{2,30}):\s', text)
    if m and m.group(1) in _SAFE_ERROR_CATEGORIES:
        return m.group(1)

    # 关键词兜底
    lower = text.lower()
    if "encode" in lower or "decode" in lower or "codec" in lower:
        return "EncodingError"
    if "import" in lower or "module" in lower:
        return "ImportError"
    if "permission" in lower or "access" in lower:
        return "PermissionError"
    if "connect" in lower or "network" in lower:
        return "NetworkError"
    if "memory" in lower:
        return "MemoryError"

    return "UnknownError"


# ── 内容脱敏 ────────────────────────────────────────────────────

def sanitize_text(text: str) -> str:
    """通用脱敏：去掉路径、URL、IP、邮件等敏感信息。"""
    if not text:
        return ""
    t = text
    # URL 必须在路径之前处理（否则 URL 的路径部分会被路径正则先吃掉）
    t = _RE_URL.sub('<URL>', t)
    t = _RE_WIN_PATH.sub('<路径>', t)
    t = _RE_UNIX_PATH.sub('<路径>', t)
    t = _RE_REL_PATH.sub('<路径>', t)
    t = _RE_IP.sub('<IP>', t)
    t = _RE_EMAIL.sub('<邮件>', t)
    t = _RE_PORT.sub(':<端口>', t)
    return t.strip()


def extract_summary_pattern(summary: str) -> str:
    """从 summary 提取模式，去掉具体内容，只保留技术结构。

    Level 2 数据处理的核心函数。保留方法论，去掉业务细节。
    """
    if not summary:
        return ""
    t = sanitize_text(summary)
    t = _RE_QUOTED.sub('<名称>', t)
    t = _RE_CAMEL.sub('<组件>', t)
    t = _RE_LONG_SNAKE.sub('<标识符>', t)
    t = re.sub(r'\s+', ' ', t).strip()
    if len(t) > 150:
        t = t[:150] + '...'
    return t


def build_event_chain(events: list[dict]) -> str:
    """从事件列表提取类型链，不含任何内容。

    [{"event_type": "error"}, {"event_type": "fix"}] → "error→fix"
    """
    if not events:
        return ""
    types = [e.get("event_type", "?") for e in events if e.get("event_type")]
    return "->".join(types[:10])


def get_platform() -> str:
    """获取平台大类，不含版本号和硬件信息。"""
    p = sys.platform
    if p == "win32":
        return "windows"
    elif p == "darwin":
        return "mac"
    elif p.startswith("linux"):
        return "linux"
    return "other"


# ── 上传包构建 ───────────────────────────────────────────────────

def build_upload_payload(
    raw: dict,
    level: int,
    opted_in: bool,
) -> dict:
    """构建最终的上传数据包，保证不含任何 Level 0 数据。

    Args:
        raw: 原始数据字典（可能含敏感信息）
        level: 数据级别（1=统计, 2=脱敏摘要）
        opted_in: 用户是否已开启 data_sharing
    """
    # Level 1：基础统计，永远安全
    payload = {
        "task_type":       raw.get("task_type", ""),
        "platform":        raw.get("platform") or get_platform(),
        "success":         bool(raw.get("success", False)),
        "retry_count":     int(raw.get("retry_count", 0)),
        "turn_count":      int(raw.get("turn_count", 0)),
        "session_id":      raw.get("session_id", ""),
        "turn_index":      int(raw.get("turn_index", 0)),
        "error_category":  extract_error_category(raw.get("error_type", "")),
        "memory_tag":      raw.get("memory_tag", ""),
    }

    # Level 2：脱敏摘要，需用户明确同意
    if level >= 2 and opted_in:
        raw_summary = raw.get("summary", "")
        if raw_summary:
            pattern = extract_summary_pattern(raw_summary)
            if pattern and len(pattern) > 10:
                payload["summary_pattern"] = pattern

        raw_steps = raw.get("key_steps", [])
        payload["step_count"] = len(raw_steps)

        events = raw.get("events", [])
        if events:
            payload["event_chain"] = build_event_chain(events)

    # 安全审计：Level 0 字段绝对不出现在 payload 里
    for forbidden in ["task_description", "summary", "error_type",
                      "key_steps", "tool_sequence", "code_snippet"]:
        payload.pop(forbidden, None)

    return payload
