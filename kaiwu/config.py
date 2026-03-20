"""配置管理 — 读取 ~/.kaiwu/config.toml，定义常量和商业化计划

支持多 Provider 配置：
  [providers.deepseek]
  [providers.openai]
  [providers.claude]
  [providers.custom]

以及 Coding 软件配置：
  [coding_software.claude_code]
  [coding_software.cursor]
"""

import os
import sys
from pathlib import Path
from typing import Any, Optional

from loguru import logger

# ── 路径常量 ──────────────────────────────────────────────────────

KAIWU_HOME = Path(os.environ.get("KAIWU_HOME", Path.home() / ".kaiwu"))
CONFIG_PATH = KAIWU_HOME / "config.toml"
USAGE_PATH = KAIWU_HOME / "usage.json"
LOG_PATH = KAIWU_HOME / "kaiwu.log"
ERROR_KB_PATH = KAIWU_HOME / "error_kb.json"
EXPERIENCE_PATH = KAIWU_HOME / "experiences.json"
PROFILE_PATH = KAIWU_HOME / "profile.json"
MEMORY_PATH = KAIWU_HOME / "memory.json"
ENRICHMENTS_PATH = KAIWU_HOME / "scene_enrichments.json"
SESSIONS_DIR = KAIWU_HOME / "sessions"

# ── 上下文压缩相关 ────────────────────────────────────────────────
CONDENSE_THRESHOLD = 15        # 触发压缩的轮数
CONDENSE_KEEP_RECENT = 5       # 压缩后保留的最近轮数（原文）
MAX_INJECT_TOKENS = 800        # 注入上下文的 token 预算（~2400 字符）
MAX_OBSERVATION_TOKENS = 500   # 单条观察的最大 token（~1500 字符）

# ── 记忆分层 ─────────────────────────────────────────────────────
MEMORY_LAYER_ANCHOR = "anchor"        # 决策锚点：永久保留，高权重
MEMORY_LAYER_EXP = "experience"       # 经验摘要：中权重，参与 few-shot
MEMORY_LAYER_LOG = "log"              # 操作日志：低权重，可定期清理
MEMORY_LAYER_METHOD = "methodology"   # 方法论模式层

# 包内数据目录
PACKAGE_DIR = Path(__file__).parent
DATA_DIR = PACKAGE_DIR.parent / "data"
SCENES_DIR = PACKAGE_DIR / "scenes"
KNOWLEDGE_DIR = PACKAGE_DIR / "knowledge"

# 噪声目录集合（用于文件树过滤）
NOISE_DIRS: frozenset[str] = frozenset({
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    "venv", ".venv", "env", ".env",
    "dist", "build", ".next", ".nuxt", ".output",
    ".cache", ".parcel-cache", ".turbo",
    "target", ".idea", ".vscode",
    "coverage", ".coverage", "htmlcov",
    "eggs", ".eggs", "logs", "tmp", "temp",
})

# ── 计划 ──────────────────────────────────────────────────────────

PLAN_FREE = "free"          # 免费版（v1.0 默认，功能完整）
PLAN_BYOK = "byok"          # 自带 DeepSeek Key

# ── 默认配置 ─────────────────────────────────────────────────────

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_MAX_TOKENS = 600
DEFAULT_TIMEOUT = 30

# ── 主模型能力分级 ─────────────────────────────────────────────
# 三级策略：
#   strong — 自身能力足够（Opus/GPT-4o级），kaiwu 只做知识库+压缩+本地匹配
#   medium — 中等能力，kaiwu 提供规划但不蒸馏
#   weak   — 需要全套服务（默认）
#
# 用户/主AI 应直接传 host_level="strong"/"medium"/"weak"
# 兼容：也可传 host_model="claude-opus-4-6"，自动推断等级


def infer_host_level(host_level: str = "", host_model: str = "") -> str:
    """推断主模型能力等级

    优先用显式 host_level，其次从 host_model 名称推断。
    返回 "strong" / "medium" / "weak"
    """
    # 显式传了等级，直接用
    if host_level in ("strong", "medium", "weak"):
        return host_level

    # 没传等级，从模型名推断
    if not host_model:
        return "weak"

    m = host_model.lower()

    # ── 弱模型：明确的低端标识（优先检测，防止 "o4-mini" 被误判强） ──
    import re
    _weak_patterns = (
        r"(?<!ge)mini",          # mini 但排除 gemini（ge + mini）
        r"lite", r"nano", r"tiny", r"small",
        r"flash", r"haiku",
        r"-3\.5",                # gpt-3.5 等
        r"-(?:7|8|14)b",         # 小参数开源
    )
    has_weak = any(re.search(p, m) for p in _weak_patterns)

    # ── 强模型：旗舰级推理能力 ──
    # 用「档次关键词」而非枚举具体模型，新模型自动适配
    _strong_patterns = (
        r"opus",                 # claude opus
        r"ultra",                # gemini ultra
        r"\bmax\b",              # llama-max 等（\b 防止匹配 "maximum"）
        r"\bo[134]-",            # o1-xxx, o3-xxx, o4-xxx（推理系列，横杠避免误匹配）
        r"deepseek-r1",          # 完整匹配，避免 "r1" 误伤
        r"thinking",             # qwen-thinking 等
        r"gpt-4o", r"gpt-4-turbo", r"gpt-4\.1",
        r"sonnet",               # claude sonnet 系列
        r"gemini-2",             # gemini 2.x
        r"-pro(?!se)",           # xxx-pro（排除 prose 等词），如 gemini-pro, qwen-pro
        r"qwen-?(?:max|plus|turbo)",  # qwen 高端系列
        r"glm-?4",               # glm-4 系列
        r"yi-large",             # 零一万物大模型
        r"abab\d*-",             # minimax abab 系列
        r"ernie-?(?:4|bot)",     # 文心一言
        r"spark-?(?:4|max|pro)", # 讯飞星火
        r"hunyuan-(?:pro|turbo)",# 腾讯混元
    )
    has_strong = any(re.search(p, m) for p in _strong_patterns)

    # ── 判定逻辑 ──
    if has_weak and not has_strong:
        return "weak"
    if has_strong and not has_weak:
        return "strong"
    if has_strong and has_weak:
        # 冲突时（如 "o4-mini"）弱信号优先
        return "weak"
    # 模糊地带（如 qwen-72b、llama-70b、deepseek-chat）→ medium
    return "medium"


def is_same_family(host_model: str, backend_model: str) -> bool:
    """判断主模型与 kaiwu 后端模型是否同系列（同模型规划无增益）

    同系列时：规划走轻量（知识库+经验），诊断保留 LLM 兜底
    """
    if not host_model or not backend_model:
        return False
    h, b = host_model.lower(), backend_model.lower()

    # 提取厂商前缀（第一段）
    def _vendor(m: str) -> str:
        for sep in ("-", "_", "/"):
            if sep in m:
                return m.split(sep, 1)[0]
        return m

    return _vendor(h) == _vendor(b)


# ── Provider 默认值 ──────────────────────────────────────────────

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "api_format": "openai",
    },
    "claude": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-20250514",
        "api_format": "anthropic",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_format": "openai",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "api_format": "openai",
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "api_format": "openai",
    },
}

class Config:
    """配置管理器，读取 ~/.kaiwu/config.toml"""

    def __init__(self):
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self):
        """加载配置文件"""
        if not CONFIG_PATH.exists():
            logger.debug(f"配置文件不存在: {CONFIG_PATH}，使用默认配置")
            return

        try:
            if sys.version_info >= (3, 11):
                import tomllib
            else:
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib  # type: ignore

            with open(CONFIG_PATH, "rb") as f:
                self._data = tomllib.load(f)
            logger.debug(f"已加载配置: {CONFIG_PATH}")
        except Exception as e:
            logger.warning(f"加载配置文件失败: {e}")

        # 旧格式自动迁移
        self._migrate_legacy()

    def _migrate_legacy(self):
        """将旧格式 [deepseek] 迁移到 [providers.deepseek]"""
        if "deepseek" not in self._data:
            return
        # 已有 providers.deepseek 则跳过
        if self._data.get("providers", {}).get("deepseek"):
            return

        old = self._data.pop("deepseek")
        if not isinstance(old, dict):
            return

        providers = self._data.setdefault("providers", {})
        providers["deepseek"] = {
            "api_key": old.get("api_key", ""),
            "base_url": old.get("base_url", DEFAULT_DEEPSEEK_BASE_URL),
            "model": old.get("model", DEFAULT_DEEPSEEK_MODEL),
            "api_format": "openai",
        }
        # 设置默认活跃提供商
        self._data.setdefault("active_provider", "deepseek")

        logger.info("已将旧格式 [deepseek] 迁移到 [providers.deepseek]")
        self._save()

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点分路径: config.get('providers.deepseek.api_key')"""
        keys = key.split(".")
        val = self._data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
            if val is None:
                return default
        return val

    def set(self, key: str, value: Any):
        """设置配置值并保存"""
        keys = key.split(".")
        d = self._data
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value
        self._save()

    def _save(self):
        """保存配置到 TOML 文件（支持两级嵌套 section）"""
        KAIWU_HOME.mkdir(parents=True, exist_ok=True)
        try:
            lines: list[str] = []
            # 先写顶层标量值
            for key, value in self._data.items():
                if not isinstance(value, dict):
                    lines.append(f"{key} = {_toml_value(value)}")

            if lines:
                lines.append("")

            # 写 section（一级和两级嵌套）
            for section, values in self._data.items():
                if not isinstance(values, dict):
                    continue
                # 检查是否是两级嵌套（如 providers, coding_software）
                has_nested = any(isinstance(v, dict) for v in values.values())
                if has_nested:
                    for sub_name, sub_values in values.items():
                        if isinstance(sub_values, dict):
                            lines.append(f"[{section}.{sub_name}]")
                            for k, v in sub_values.items():
                                lines.append(f"{k} = {_toml_value(v)}")
                            lines.append("")
                        else:
                            # 混合情况（section 下既有子表又有标量）不太常见，但处理一下
                            pass
                else:
                    lines.append(f"[{section}]")
                    for k, v in values.items():
                        lines.append(f"{k} = {_toml_value(v)}")
                    lines.append("")

            CONFIG_PATH.write_text("\n".join(lines), encoding="utf-8")
        except Exception as e:
            logger.warning(f"保存配置失败: {e}")

    # ── 活跃提供商相关属性 ──────────────────────────────────────────

    @property
    def active_provider_name(self) -> str:
        """当前活跃的提供商名称"""
        return self._data.get("active_provider", "deepseek")

    def _active_provider(self) -> dict[str, Any]:
        """获取活跃提供商的配置字典"""
        name = self.active_provider_name
        return self.get(f"providers.{name}") or {}

    @property
    def llm_api_key(self) -> Optional[str]:
        """当前活跃提供商的 API Key"""
        # 环境变量优先（兼容旧逻辑）
        env_key = os.environ.get("DEEPSEEK_API_KEY")
        if env_key:
            return env_key
        return self._active_provider().get("api_key") or None

    @property
    def llm_base_url(self) -> str:
        """当前活跃提供商的 Base URL"""
        env_url = os.environ.get("DEEPSEEK_BASE_URL")
        if env_url:
            return env_url
        url = self._active_provider().get("base_url")
        if url:
            return url
        defaults = PROVIDER_DEFAULTS.get(self.active_provider_name, {})
        return defaults.get("base_url", DEFAULT_DEEPSEEK_BASE_URL)

    @property
    def llm_model(self) -> str:
        """当前活跃提供商的模型名"""
        model = self._active_provider().get("model")
        if model:
            return model
        defaults = PROVIDER_DEFAULTS.get(self.active_provider_name, {})
        return defaults.get("model", DEFAULT_DEEPSEEK_MODEL)

    @property
    def llm_api_format(self) -> str:
        """当前活跃提供商的 API 格式: 'openai' 或 'anthropic'"""
        fmt = self._active_provider().get("api_format")
        if fmt:
            return fmt
        defaults = PROVIDER_DEFAULTS.get(self.active_provider_name, {})
        return defaults.get("api_format", "openai")

    # ── 旧属性别名（向后兼容） ──────────────────────────────────────

    @property
    def deepseek_api_key(self) -> Optional[str]:
        """获取 DeepSeek API Key（兼容旧代码，委托给 llm_api_key）"""
        return self.llm_api_key

    @property
    def deepseek_base_url(self) -> str:
        """获取 DeepSeek Base URL（兼容旧代码，委托给 llm_base_url）"""
        return self.llm_base_url

    @property
    def deepseek_model(self) -> str:
        """获取 DeepSeek 模型名（兼容旧代码，委托给 llm_model）"""
        return self.llm_model

    @property
    def plan(self) -> str:
        """获取当前计划"""
        license_key = self.get("license.key")
        if license_key:
            # license 验证逻辑尚未实现，有 key 也按免费版处理
            return PLAN_FREE
        if self.llm_api_key:
            return PLAN_BYOK
        return PLAN_FREE

    @property
    def member_token(self) -> Optional[str]:
        """获取 license key（v1.0 预留，暂不启用）"""
        return self.get("license.key")



def _toml_value(v: Any) -> str:
    """将 Python 值转为 TOML 格式字符串"""
    if isinstance(v, str):
        # 转义反斜杠和双引号
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    elif isinstance(v, bool):
        return "true" if v else "false"
    elif isinstance(v, (int, float)):
        return str(v)
    elif isinstance(v, list):
        items = ", ".join(_toml_value(item) for item in v)
        return f"[{items}]"
    elif v is None:
        return '""'
    else:
        escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'


# 全局单例
_config: Optional[Config] = None


def get_config() -> Config:
    """获取全局配置单例"""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    """重新加载配置（向导保存后刷新）"""
    global _config
    _config = Config()
    return _config
