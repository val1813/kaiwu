"""经验库 — 成功轨迹存储 + 智能去重 + Tag 分类注入

v0.2 三项升级（借鉴 mem0 理念，编程场景专用实现）：
1. 四态决策：ADD/UPDATE/DELETE/NONE，写入前先比对，经验库越用越精炼
2. Tag 体系：5 类标签 + 优先级矩阵，debug 任务优先看 error_pattern
3. Project 过滤：按项目名隔离经验，giotrip 项目不会看到 cl-kaiwu 的经验

存储在 ~/.kaiwu/experiences.json。
"""

import hashlib
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from loguru import logger

from kaiwu.config import EXPERIENCE_PATH, DATA_DIR

MAX_EXPERIENCES = 200

# ── 事实性内容过滤（防止 DeepSeek 知识与主 AI 冲突） ────────────────

# 匹配可能与主 AI 知识冲突的断言性内容
_FACT_ASSERTION_PATTERNS: list[re.Pattern] = [
    # 年份断言："2024标准"、"2023年最新"
    re.compile(r'20\d{2}\s*(?:年|标准|最新|推荐|版)'),
    # 性能倍数断言："快10倍"、"提升50%"
    re.compile(r'(?:快|慢|提升|降低|减少|增加)\s*\d+\s*(?:倍|%|百分)'),
    # 主观排名："最好的"、"最优的"、"首选"、"唯一正确"
    re.compile(r'(?:最好的|最优的|最佳的|首选|唯一正确|必须用|一定要用|强烈推荐)'),
    # "是标准"、"是主流"等定性断言
    re.compile(r'是\s*(?:标准|主流|最新|默认|唯一)'),
]


def _sanitize_assertion(text: str) -> str:
    """过滤文本中的事实性断言，替换为中性表述

    不删除整行，而是把断言词替换为温和的描述，保留可用信息。
    """
    result = text
    # 年份断言 → 去掉年份
    result = re.sub(r'20\d{2}\s*(?:年|标准|最新|推荐)', '', result)
    # "快N倍" → "显著提升效率"
    result = re.sub(r'(?:快|提升)\s*\d+\s*(?:倍|%|百分[\u4e00-\u9fff]*)(?:以上|左右)?', '显著提升效率', result)
    result = re.sub(r'(?:慢|降低|减少)\s*\d+\s*(?:倍|%|百分[\u4e00-\u9fff]*)(?:以上|左右)?', '有所降低', result)
    # "最好的/首选/唯一正确" → "常用的"
    result = re.sub(r'(?:最好的|最优的|最佳的|首选|唯一正确的?)', '常用的', result)
    # "必须用/一定要用" → "建议用"
    result = re.sub(r'(?:必须用|一定要用|强烈推荐)', '建议用', result)
    # "是标准/是主流" → "是常见方案"
    result = re.sub(r'是\s*(?:标准|主流|最新|默认|唯一)\s*', '是常见的', result)
    return result

# ── 记忆分类常量 ──────────────────────────────────────────────────

MEMORY_TAG_IMPL = "implementation_detail"   # 具体实现方案、技术选型
MEMORY_TAG_PREF = "user_preference"         # 用户偏好（编码风格、框架倾向）
MEMORY_TAG_CTX  = "project_context"         # 项目背景（架构、约定）
MEMORY_TAG_ERR  = "error_pattern"           # 错误模式
MEMORY_TAG_PROC = "procedure"               # 通用流程（如"部署流程"）
MEMORY_TAG_METHOD = "methodology"           # 方法论模式: "在X情境下，做Y比做Z好"

# ── Tag 优先级矩阵：{task_type: {tag: weight}} ──────────────────

_TAG_PRIORITY = {
    "backend_api":  {MEMORY_TAG_IMPL: 1.0, MEMORY_TAG_ERR: 0.8, MEMORY_TAG_PREF: 0.6, MEMORY_TAG_CTX: 0.5, MEMORY_TAG_PROC: 0.3, MEMORY_TAG_METHOD: 0.9},
    "web":          {MEMORY_TAG_IMPL: 1.0, MEMORY_TAG_ERR: 0.8, MEMORY_TAG_PREF: 0.6, MEMORY_TAG_CTX: 0.5, MEMORY_TAG_PROC: 0.3, MEMORY_TAG_METHOD: 0.9},
    "react":        {MEMORY_TAG_IMPL: 1.0, MEMORY_TAG_ERR: 0.8, MEMORY_TAG_PREF: 0.7, MEMORY_TAG_CTX: 0.5, MEMORY_TAG_PROC: 0.3, MEMORY_TAG_METHOD: 0.9},
    "debug":        {MEMORY_TAG_ERR: 1.0, MEMORY_TAG_IMPL: 0.7, MEMORY_TAG_PREF: 0.4, MEMORY_TAG_CTX: 0.5, MEMORY_TAG_PROC: 0.3, MEMORY_TAG_METHOD: 0.95},
    "code_review":  {MEMORY_TAG_PREF: 1.0, MEMORY_TAG_IMPL: 0.7, MEMORY_TAG_ERR: 0.6, MEMORY_TAG_CTX: 0.5, MEMORY_TAG_PROC: 0.4, MEMORY_TAG_METHOD: 0.85},
    "refactor":     {MEMORY_TAG_PROC: 1.0, MEMORY_TAG_IMPL: 0.8, MEMORY_TAG_ERR: 0.6, MEMORY_TAG_CTX: 0.7, MEMORY_TAG_PREF: 0.5, MEMORY_TAG_METHOD: 0.9},
    "shell_script": {MEMORY_TAG_PROC: 1.0, MEMORY_TAG_IMPL: 0.7, MEMORY_TAG_ERR: 0.8, MEMORY_TAG_CTX: 0.5, MEMORY_TAG_PREF: 0.3, MEMORY_TAG_METHOD: 0.85},
}
_DEFAULT_TAG_PRIORITY = {MEMORY_TAG_IMPL: 0.8, MEMORY_TAG_ERR: 0.7, MEMORY_TAG_PREF: 0.5, MEMORY_TAG_CTX: 0.6, MEMORY_TAG_PROC: 0.4, MEMORY_TAG_METHOD: 0.85}


# ── 四态决策 Prompt ──────────────────────────────────────────────

_MEMORY_DECISION_SYSTEM = """\
你是编程经验库管理员，决定如何处理新经验条目。四种操作：

**ADD**：全新知识点，与现有无重叠。
**UPDATE**：同场景但更详细/更新，合并到 merged_text，保留 target_id。
**DELETE**：与现有条目直接矛盾。
**NONE**：与现有高度相似，无增量价值。

# 示例

现有：[{"id": "exp_002", "text": "FastAPI 部署需要 uvicorn"}]
新经验：FastAPI 生产部署，uvicorn+gunicorn 多进程，Windows 用 waitress
决策：{"operation": "UPDATE", "target_id": "exp_002", "merged_text": "FastAPI 部署：开发用 uvicorn，生产用 uvicorn+gunicorn，Windows 用 waitress", "reason": "同场景更完整"}

现有：[{"id": "exp_004", "text": "pip 安装慢，配置清华源"}]
新经验：pip 安装慢可以用清华镜像源加速
决策：{"operation": "NONE", "reason": "与现有高度重复"}

只返回 JSON：
{"operation": "ADD|UPDATE|DELETE|NONE", "target_id": "exp_xxx或null", "merged_text": "合并后内容或null", "reason": "一句话原因"}
"""


# ── Tag 自动推断 ──────────────────────────────────────────────────

def infer_memory_tag(task_type: str, summary: str, success: bool) -> str:
    """根据任务类型和摘要内容自动推断 memory_tag（零 token 消耗）

    规则优先级：失败直接归 error > 显式关键词 > task_type 映射 > 默认值
    """
    summary_lower = (summary or "").lower()

    if not success:
        return MEMORY_TAG_ERR

    # 方法论模式识别
    _method_kw = {"方法论", "策略", "approach", "pattern", "methodology"}
    if any(kw in summary_lower for kw in _method_kw):
        return MEMORY_TAG_METHOD

    _kw_map = [
        (["错误", "报错", "失败", "error", "exception", "traceback",
          "坑", "bug", "fix", "修复", "注意", "警告"], MEMORY_TAG_ERR),
        (["偏好", "习惯", "风格", "prefer", "always", "never",
          "不用", "避免使用", "命名规范", "代码风格"], MEMORY_TAG_PREF),
        (["项目", "架构", "技术栈", "版本", "依赖", "配置", "约定",
          "project", "stack", "version", "config"], MEMORY_TAG_CTX),
        (["流程", "步骤", "pipeline", "workflow", "deploy", "部署",
          "发布", "上线"], MEMORY_TAG_PROC),
    ]

    for keywords, tag in _kw_map:
        if any(kw in summary_lower for kw in keywords):
            return tag

    _type_tag_map = {
        "debug": MEMORY_TAG_ERR,
        "code_review": MEMORY_TAG_PREF,
        "refactor": MEMORY_TAG_PROC,
        "shell_script": MEMORY_TAG_PROC,
    }

    return _type_tag_map.get(task_type, MEMORY_TAG_IMPL)


# ── 数据模型 ──────────────────────────────────────────────────────

@dataclass
class ToolStep:
    """单个工具调用步骤"""
    tool_name: str
    params_summary: str
    result_summary: str
    success: bool

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ToolStep":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class TraceStep:
    """执行轨迹中的单步 — 由主 AI 在任务完成时上报"""
    turn: int                    # 第几轮 (1-indexed)
    action: str                  # 做了什么: "读取 config.py", "修改 auth 模块"
    outcome: str                 # 结果: "发现 bug 在第42行", "测试仍失败"
    success: bool                # 这一步是否达到预期
    pivot: bool = False          # 主 AI 自标: "这里我换了方向"

    def to_dict(self) -> dict:
        return {
            "turn": self.turn,
            "action": self.action[:120],
            "outcome": self.outcome[:120],
            "success": self.success,
            "pivot": self.pivot,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TraceStep":
        return cls(
            turn=d.get("turn", 0),
            action=d.get("action", "")[:120],
            outcome=d.get("outcome", "")[:120],
            success=d.get("success", True),
            pivot=d.get("pivot", False),
        )


@dataclass
class Experience:
    """单条经验记录"""
    exp_id: str
    task_type: str
    task_description: str
    timestamp: float = field(default_factory=time.time)

    # 第一层：问题理解
    problem_pattern: str = ""
    problem_keywords: list[str] = field(default_factory=list)

    # 第二层：错误定位
    localization_strategy: str = ""
    files_involved: list[str] = field(default_factory=list)

    # 第三层：修改策略
    fix_strategy: str = ""
    tool_sequence: list[ToolStep] = field(default_factory=list)
    key_steps: list[str] = field(default_factory=list)

    # 统计
    turns_taken: int = 0
    hit_count: int = 0
    success: bool = True

    # v0.2 新增：蒸馏后的摘要（与 fix_strategy 类似但更简洁）
    summary: str = ""

    # v0.3 新增：失败时的错误摘要（前车之鉴用）
    error_summary: str = ""

    # v0.2 新增：记忆分类 + 项目隔离 + 软删除
    memory_tag: str = MEMORY_TAG_IMPL
    project_name: str = ""
    deprecated: bool = False
    deprecated_at: float = 0.0

    # v0.3 新增：助攻率度量
    inject_count: int = 0   # 被注入次数
    assist_count: int = 0   # 注入后任务成功的次数

    def to_dict(self) -> dict:
        d = {
            "exp_id": self.exp_id,
            "task_type": self.task_type,
            "task_description": self.task_description[:300],
            "timestamp": self.timestamp,
            "problem_pattern": self.problem_pattern[:200],
            "problem_keywords": self.problem_keywords[:10],
            "localization_strategy": self.localization_strategy[:200],
            "files_involved": self.files_involved[:10],
            "fix_strategy": self.fix_strategy[:300],
            "tool_sequence": [s.to_dict() for s in self.tool_sequence[:15]],
            "key_steps": self.key_steps[:10],
            "turns_taken": self.turns_taken,
            "hit_count": self.hit_count,
            "success": self.success,
            "summary": self.summary[:300],
            "error_summary": self.error_summary[:200],
            "memory_tag": self.memory_tag,
            "project_name": self.project_name,
        }
        if self.deprecated:
            d["deprecated"] = True
            d["deprecated_at"] = self.deprecated_at
        if self.inject_count:
            d["inject_count"] = self.inject_count
        if self.assist_count:
            d["assist_count"] = self.assist_count
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Experience":
        steps = [ToolStep.from_dict(s) for s in d.get("tool_sequence", [])]
        return cls(
            exp_id=d.get("exp_id", ""),
            task_type=d.get("task_type", "general"),
            task_description=d.get("task_description", ""),
            timestamp=d.get("timestamp", 0),
            problem_pattern=d.get("problem_pattern", ""),
            problem_keywords=d.get("problem_keywords", []),
            localization_strategy=d.get("localization_strategy", ""),
            files_involved=d.get("files_involved", []),
            fix_strategy=d.get("fix_strategy", ""),
            tool_sequence=steps,
            key_steps=d.get("key_steps", []),
            turns_taken=d.get("turns_taken", 0),
            hit_count=d.get("hit_count", 0),
            success=d.get("success", True),
            summary=d.get("summary", d.get("fix_strategy", "")),
            error_summary=d.get("error_summary", ""),
            memory_tag=d.get("memory_tag", MEMORY_TAG_IMPL),
            project_name=d.get("project_name", ""),
            deprecated=d.get("deprecated", False),
            deprecated_at=d.get("deprecated_at", 0.0),
            inject_count=d.get("inject_count", 0),
            assist_count=d.get("assist_count", 0),
        )

    def to_few_shot(self) -> str:
        """将经验蒸馏为可注入的 few-shot 文本"""
        parts = []
        parts.append(f"[任务] {self.task_description[:150]}")
        if self.problem_pattern:
            parts.append(f"[问题模式] {self.problem_pattern}")
        if self.localization_strategy:
            parts.append(f"[定位方法] {self.localization_strategy}")
        if self.fix_strategy:
            parts.append(f"[修改策略] {self.fix_strategy}")
        if self.key_steps:
            step_lines = [f"  {i}. {s}" for i, s in enumerate(self.key_steps, 1)]
            parts.append("[关键步骤]\n" + "\n".join(step_lines))
        elif self.tool_sequence:
            key_steps = [s for s in self.tool_sequence if s.success][:5]
            if key_steps:
                step_lines = [
                    f"  {i}. {s.tool_name}({s.params_summary}) -> {s.result_summary}"
                    for i, s in enumerate(key_steps, 1)
                ]
                parts.append("[关键步骤]\n" + "\n".join(step_lines))
        parts.append(f"[效率] {self.turns_taken} 轮完成")
        return "\n".join(parts)

    @property
    def effective_summary(self) -> str:
        """取最佳可用摘要"""
        return self.summary or self.fix_strategy or self.problem_pattern or ""


# ── 关键词提取 ────────────────────────────────────────────────────

def _extract_keywords(text: str) -> list[str]:
    """从任务描述中提取关键词（英文 unigram+bigram，中文 2-gram 滑动窗口）"""
    stop_words = {
        "的", "是", "在", "了", "和", "与", "将", "把", "被",
        "用", "对", "中", "里", "从", "到", "写", "改", "加", "删",
        "一", "个", "这", "那", "有", "不", "要", "为", "会", "可",
        "a", "an", "the", "is", "are", "in", "to", "of", "and", "for",
        "with", "from", "by", "on", "at", "it", "this", "that",
        "file", "files", "function", "class", "code", "task", "use",
    }

    en_words = re.findall(r'[a-zA-Z_]\w+', text.lower())
    en_tokens = [w for w in en_words if w not in stop_words and len(w) >= 2]

    cn_chunks = re.findall(r'[\u4e00-\u9fff]+', text)
    cn_tokens: list[str] = []
    for chunk in cn_chunks:
        if len(chunk) == 1:
            if chunk not in stop_words:
                cn_tokens.append(chunk)
        elif len(chunk) == 2:
            cn_tokens.append(chunk)
        else:
            for i in range(len(chunk) - 1):
                cn_tokens.append(chunk[i:i + 2])

    seen: set[str] = set()
    tokens: list[str] = []
    for w in en_tokens + cn_tokens:
        if w not in seen:
            seen.add(w)
            tokens.append(w)

    en_bigrams = [f"{en_tokens[i]}_{en_tokens[i+1]}"
                  for i in range(len(en_tokens) - 1)]
    for bg in en_bigrams:
        if bg not in seen:
            seen.add(bg)
            tokens.append(bg)

    return tokens[:30]


def _make_exp_id(task: str, task_type: str) -> str:
    key = f"{task_type}:{task.strip()[:200].lower()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _keyword_overlap(text_a: str, text_b: str) -> float:
    """计算两段文本的关键词重叠率（0~1），零 token 消耗"""
    words_a = set(_extract_keywords(text_a))
    words_b = set(_extract_keywords(text_b))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(len(words_a), len(words_b))


# ── ExperienceStore ──────────────────────────────────────────────

class ExperienceStore:
    """经验库：存储、检索、四态决策、Tag 分类注入"""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or EXPERIENCE_PATH
        self._data: dict[str, Experience] = {}
        self._load()
        self._merge_preset()
        self._tfidf = _TfIdfIndex()
        self._build_tfidf_index()

    def _build_tfidf_index(self):
        """从现有数据构建 TF-IDF 索引"""
        for exp_id, exp in self._data.items():
            if not exp.deprecated:
                text = f"{exp.task_description} {exp.effective_summary} {' '.join(exp.key_steps or [])}"
                self._tfidf.add(exp_id, text)

    def _load(self):
        """加载经验库"""
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for eid, edata in data.items():
                    try:
                        self._data[eid] = Experience.from_dict(edata)
                    except Exception:
                        pass
                logger.debug(f"加载 {len(self._data)} 条经验")
        except Exception as e:
            logger.debug(f"加载经验库失败: {e}")

    def _merge_preset(self):
        """合并预置经验库 data/experience.json"""
        preset_path = DATA_DIR / "experience.json"
        if not preset_path.exists():
            return
        try:
            preset = json.loads(preset_path.read_text(encoding="utf-8"))
            for entry in preset.get("entries", []):
                eid = entry.get("exp_id", _make_exp_id(
                    entry.get("task_description", ""), entry.get("task_type", "")
                ))
                if eid not in self._data:
                    self._data[eid] = Experience.from_dict(entry)
            logger.debug(f"合并预置经验库: {len(preset.get('entries', []))} 条")
        except Exception as e:
            logger.debug(f"加载预置经验库失败: {e}")

    def _save(self):
        """保存经验库"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = {eid: exp.to_dict() for eid, exp in self._data.items()}
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"保存经验库失败: {e}")

    # ── 四态决策相关 ────────────────────────────────────────────

    def find_similar(self, task: str, task_type: str, limit: int = 8) -> list[dict]:
        """检索与新经验相似的已有经验，供四态决策使用

        策略（零向量库依赖）：
        1. 同 task_type 的活跃经验优先
        2. 按关键词重叠度排序
        """
        active = [
            e for e in self._data.values()
            if not e.deprecated and e.effective_summary
        ]

        candidates = [e for e in active if e.task_type == task_type]
        if len(candidates) < limit:
            others = [e for e in active if e.task_type != task_type]
            others.sort(key=lambda e: e.timestamp, reverse=True)
            candidates.extend(others[:limit - len(candidates)])

        if not candidates:
            return []

        task_words = set(_extract_keywords(task))

        def overlap_score(exp: Experience) -> float:
            exp_text = exp.effective_summary + " ".join(exp.key_steps or [])
            exp_words = set(_extract_keywords(exp_text))
            if not task_words or not exp_words:
                return 0.0
            return len(task_words & exp_words) / max(len(task_words), 1)

        candidates.sort(key=overlap_score, reverse=True)

        return [
            {
                "exp_id": e.exp_id,
                "text": e.effective_summary[:100],
                "task_type": e.task_type,
                "memory_tag": e.memory_tag,
            }
            for e in candidates[:limit]
        ]

    def decide_memory_operation(
        self,
        new_summary: str,
        new_key_steps: list[str],
        task_type: str,
        similar_memories: list[dict],
    ) -> dict:
        """四态决策：ADD / UPDATE / DELETE / NONE

        **Opus 改进**：先做关键词快速去重，重叠 > 80% 直接 NONE，
        省去 LLM 调用。只有不确定时才调 DeepSeek。
        """
        # ── 快速路径：关键词去重（零 token 消耗）──
        for m in similar_memories:
            if m["task_type"] == task_type:
                overlap = _keyword_overlap(new_summary, m["text"])
                if overlap > 0.8:
                    logger.debug(f"快速去重命中: overlap={overlap:.2f}, exp={m['exp_id']}")
                    return {"operation": "NONE", "reason": f"keyword_dedup:{overlap:.2f}"}

        # ── 慢速路径：LLM 决策 ──
        from kaiwu.llm_client import call_llm
        from kaiwu.quota import check_quota, record_call
        from kaiwu.config import DEFAULT_TIMEOUT

        allowed, _ = check_quota()
        if not allowed or not similar_memories:
            return {"operation": "ADD", "reason": "no_quota_or_no_similar"}

        existing_str = "\n".join([
            f'  {{"id": "{m["exp_id"]}", "text": "{m["text"][:100]}", "type": "{m["task_type"]}"}}'
            for m in similar_memories[:6]
        ])

        prompt = f"""{_MEMORY_DECISION_SYSTEM}

# 现有记忆库（相关条目）

```json
[
{existing_str}
]
```

# 新检索到的事实

```
任务类型：{task_type}
经验摘要：{new_summary[:200]}
关键步骤：{"; ".join(new_key_steps[:3])}
```"""

        try:
            raw = call_llm(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.1,
                timeout=DEFAULT_TIMEOUT,
                purpose="memory_decision",
            )
            record_call()

            text = raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines)

            result = json.loads(text)
            op = result.get("operation", "ADD").upper()
            if op not in ("ADD", "UPDATE", "DELETE", "NONE"):
                op = "ADD"

            return {
                "operation": op,
                "target_exp_id": result.get("target_id"),
                "merged_text": result.get("merged_text"),
                "reason": result.get("reason", ""),
            }

        except Exception as e:
            logger.debug(f"四态决策失败，降级为 ADD: {e}")
            return {"operation": "ADD", "reason": f"error:{e}"}

    def _soft_delete(self, exp_id: str) -> bool:
        """软删除：标记 deprecated，不物理删除"""
        if exp_id in self._data:
            self._data[exp_id].deprecated = True
            self._data[exp_id].deprecated_at = time.time()
            self._tfidf.remove(exp_id)
            self._save()
            return True
        return False

    def _update_summary(self, exp_id: str, new_summary: str) -> bool:
        """更新指定条目的摘要（写入前过滤断言性内容）"""
        if exp_id in self._data:
            exp = self._data[exp_id]
            sanitized = _sanitize_assertion(new_summary)
            exp.summary = sanitized
            exp.fix_strategy = sanitized
            exp.timestamp = time.time()
            self._save()
            return True
        return False

    # ── 记录 ────────────────────────────────────────────────────

    def record(
        self,
        task: str,
        task_type: str,
        success: bool,
        summary: str = "",
        key_steps: Optional[list[str]] = None,
        turns: int = 0,
        error_summary: str = "",
        memory_tag: str = "",
        project_name: str = "",
    ) -> Optional[Experience]:
        """记录一次任务结果

        v0.2 升级：写入前做四态决策，避免经验库膨胀。
        新增 memory_tag / project_name 参数。

        Args:
            task: 原始任务描述
            task_type: 任务分类
            success: 是否成功
            summary: DeepSeek 提炼的经验摘要
            key_steps: 关键步骤列表
            turns: 完成轮数
            error_summary: 失败时的错误摘要
            memory_tag: 记忆分类（空则自动推断）
            project_name: 所属项目名（空则全局共享）
        """
        if len(task.strip()) < 15:
            return None

        # 自动推断 tag
        if not memory_tag:
            effective_summary = summary or error_summary
            memory_tag = infer_memory_tag(task_type, effective_summary, success)

        suffix = "" if success else ":FAIL"
        exp_id = _make_exp_id(task + suffix, task_type)

        # 完全相同的 exp_id 已存在 → 更新命中计数
        if exp_id in self._data:
            existing = self._data[exp_id]
            existing.hit_count += 1
            if success and turns > 0 and turns < existing.turns_taken:
                existing.turns_taken = turns
                existing.fix_strategy = summary or existing.fix_strategy
                existing.summary = summary or existing.summary
            self._save()
            return existing

        # ── 四态决策（有摘要时才做，否则直接 ADD）──
        if summary:
            similar = self.find_similar(task, task_type, limit=8)
            if similar:
                decision = self.decide_memory_operation(
                    summary, key_steps or [], task_type, similar,
                )
                op = decision["operation"]
                logger.debug(f"记忆决策: {op} | {decision['reason']}")

                if op == "NONE":
                    logger.info(f"经验已存在(NONE): {summary[:50]}")
                    return None

                if op == "DELETE" and decision.get("target_exp_id"):
                    self._soft_delete(decision["target_exp_id"])
                    logger.info(f"矛盾经验已废弃: {decision['target_exp_id']}")
                    if not success:
                        return None

                if op == "UPDATE" and decision.get("target_exp_id"):
                    merged = decision.get("merged_text") or summary
                    self._update_summary(decision["target_exp_id"], merged)
                    logger.info(f"经验已更新: {decision['target_exp_id']}")
                    return None

        # ADD：创建新条目（写入前过滤断言性内容）
        clean_summary = _sanitize_assertion(summary) if summary else ""
        clean_steps = [_sanitize_assertion(s) for s in key_steps] if key_steps else []
        exp = Experience(
            exp_id=exp_id,
            task_type=task_type,
            task_description=task[:300],
            problem_pattern=clean_summary[:200] if success else f"[失败] {error_summary[:150]}",
            problem_keywords=_extract_keywords(task),
            fix_strategy=clean_summary[:300] if success else f"[避免] {error_summary[:200]}",
            key_steps=clean_steps,
            turns_taken=turns,
            success=success,
            summary=clean_summary[:300],
            error_summary=error_summary[:200] if not success else "",
            memory_tag=memory_tag,
            project_name=project_name,
        )

        self._data[exp_id] = exp
        self._trim()
        self._save()
        text = f"{exp.task_description} {exp.effective_summary} {' '.join(exp.key_steps or [])}"
        self._tfidf.add(exp.exp_id, text)
        logger.info(f"记录{'成功' if success else '失败'}经验: {exp_id} [{memory_tag}]")
        return exp

    def update_distill(self, exp_id: str, summary: str, key_steps: list[str]) -> bool:
        """异步蒸馏完成后回写摘要（线程安全，写入前过滤断言）"""
        if exp_id not in self._data:
            return False
        exp = self._data[exp_id]
        sanitized = _sanitize_assertion(summary)
        exp.summary = sanitized[:300]
        exp.fix_strategy = sanitized[:300]
        exp.key_steps = key_steps or exp.key_steps
        exp.problem_pattern = sanitized[:200]
        self._save()
        return True

    # ── 检索与注入 ──────────────────────────────────────────────

    def retrieve(self, task: str, task_type: str = "", top_k: int = 2,
                 project_name: str = "") -> list[Experience]:
        """检索与当前任务最相关的经验

        v0.2：过滤 deprecated，支持 project_name 过滤
        评分：tag权重 × (类型匹配+Jaccard+成功+命中+时间衰减)
        """
        task_keywords = set(_extract_keywords(task))
        now = time.time()
        tag_priority = _TAG_PRIORITY.get(task_type, _DEFAULT_TAG_PRIORITY)
        candidates = []

        for exp in self._data.values():
            if exp.deprecated:
                continue
            # project 过滤：空名全局共享，有名只匹配同项目 + 全局
            if project_name and exp.project_name and exp.project_name != project_name:
                continue

            # ── 相关性分（必须先过关，不相关的经验再成功也不给） ──
            relevance = 0.0

            if task_type and exp.task_type == task_type:
                relevance += 3.0

            exp_keywords = set(exp.problem_keywords)
            if exp.task_description:
                exp_keywords |= set(_extract_keywords(exp.task_description))

            union = task_keywords | exp_keywords
            if union:
                jaccard = len(task_keywords & exp_keywords) / len(union)
            else:
                jaccard = 0.0
            relevance += jaccard * 10.0  # 相关性权重拉大

            # 相关性太低直接跳过（一个通用词不够）
            if relevance < 0.8:
                continue

            # ── 质量分（在相关的基础上加成） ──
            quality = 1.0
            if exp.success:
                quality += 0.5
            quality += min(exp.hit_count, 6) * 0.1

            if exp.timestamp > 0:
                age_days = (now - exp.timestamp) / 86400
                if age_days > 30:
                    quality *= 0.5
                elif age_days > 14:
                    quality *= 0.7

            # Tag 权重
            tag_weight = tag_priority.get(exp.memory_tag, 0.5)

            score = relevance * quality * tag_weight

            # 阈值：有 task_type 时严格，无 task_type 时宽松
            threshold = 2.0 if task_type else 1.2
            if score >= threshold:
                candidates.append((score, exp))

        candidates.sort(key=lambda x: x[0], reverse=True)

        # TF-IDF 精排（如果候选数 > top_k，用 TF-IDF 重排）
        if len(candidates) > top_k:
            tfidf_scores = dict(self._tfidf.query(task, top_k=len(candidates)))
            candidates = [
                (score * 0.6 + tfidf_scores.get(exp.exp_id, 0) * 10 * 0.4, exp)
                for score, exp in candidates
            ]
            candidates.sort(key=lambda x: x[0], reverse=True)

        results = []
        for _, exp in candidates[:top_k]:
            exp.hit_count += 1
            results.append(exp)

        if results:
            self._save()
            try:
                from kaiwu.llm_client import record_local_hit
                for _ in results:
                    record_local_hit()
            except Exception:
                pass

        return results

    def record_assist(self, exp_ids: list[str]) -> None:
        """记录这些经验参与了一次成功任务（助攻率度量）"""
        changed = False
        for eid in exp_ids:
            if eid in self._data:
                self._data[eid].assist_count += 1
                changed = True
        if changed:
            self._save()

    def inject_into_context(self, task: str, task_type: str = "",
                            limit: int = 3, project_name: str = "") -> str:
        """检索相关经验并生成可注入的上下文文本

        v0.3：
        - 成功经验标注为"参考建议"，失败经验标注为"⚠ 前车之鉴"
        - 加 disclaimer 防止覆盖主模型自身判断
        - 来源标注（本地经验库 vs DeepSeek蒸馏）
        """
        experiences = self.retrieve(task, task_type, top_k=limit,
                                    project_name=project_name)
        if not experiences:
            self._last_injected_ids: list[str] = []
            return ""

        # 记录注入的经验 ID，并增加 inject_count
        self._last_injected_ids = [e.exp_id for e in experiences]
        for e in experiences:
            e.inject_count += 1
        self._save()

        # 分离成功经验和失败经验
        success_exps = [e for e in experiences if e.success]
        fail_exps = [e for e in experiences if not e.success]

        parts = [
            "[历史经验参考 — 来源: 本地经验库]",
            "[注意: 以下仅含方法论和步骤参考，不含事实性断言。如有残留具体值/年份/排名请忽略，以你自身知识为准]",
        ]

        # 失败经验优先展示（前车之鉴比成功经验更重要）
        idx = 1
        if fail_exps:
            for exp in fail_exps:
                tag = exp.memory_tag
                summary = _sanitize_assertion(exp.effective_summary)
                lines = [f"{idx}. [WARNING: 前车之鉴] [{tag}] {summary[:200]}"]
                if exp.error_summary:
                    lines.append(f"   上次失败原因: {exp.error_summary[:150]}")
                if exp.key_steps:
                    steps_text = "; ".join(
                        _sanitize_assertion(s) for s in exp.key_steps[:5]
                    )
                    lines.append(f"   应避免的路径: {steps_text}")
                parts.append("\n".join(lines))
                idx += 1

        # 成功经验：分离方法论和普通经验
        method_exps = [e for e in success_exps if e.memory_tag == MEMORY_TAG_METHOD]
        normal_exps = [e for e in success_exps if e.memory_tag != MEMORY_TAG_METHOD]

        # 方法论经验（在失败经验之后、普通成功经验之前）
        for exp in method_exps:
            summary = _sanitize_assertion(exp.effective_summary)
            lines = [f"{idx}. [方法论] {summary[:200]}"]
            if exp.key_steps:
                for step in exp.key_steps[:3]:
                    lines.append(f"   {_sanitize_assertion(step)}")
            parts.append("\n".join(lines))
            idx += 1

        # 普通成功经验
        for exp in normal_exps:
            tag = exp.memory_tag
            summary = _sanitize_assertion(exp.effective_summary)

            lines = [f"{idx}. [{tag}] {summary[:200]}"]

            if exp.key_steps:
                steps_text = "; ".join(
                    _sanitize_assertion(s) for s in exp.key_steps[:5]
                )
                lines.append(f"   关键步骤: {steps_text}")

            if exp.turns_taken > 5:
                lines.append(f"   (上次用了 {exp.turns_taken} 轮才成功，建议参考上述步骤)")

            parts.append("\n".join(lines))
            idx += 1

        return "\n".join(parts)

    def get_stats(self) -> dict:
        """获取经验库统计"""
        active = [e for e in self._data.values() if not e.deprecated]
        deprecated_count = len(self._data) - len(active)
        success = sum(1 for e in active if e.success)
        fail = sum(1 for e in active if not e.success)
        type_dist: dict[str, int] = {}
        tag_dist: dict[str, int] = {}
        for e in active:
            type_dist[e.task_type] = type_dist.get(e.task_type, 0) + 1
            tag_dist[e.memory_tag] = tag_dist.get(e.memory_tag, 0) + 1
        return {
            "total": len(active),
            "deprecated": deprecated_count,
            "success": success,
            "fail": fail,
            "type_distribution": type_dist,
            "tag_distribution": tag_dist,
        }

    def _trim(self):
        """清理过期经验（deprecated 优先清除）"""
        if len(self._data) <= MAX_EXPERIENCES:
            return
        sorted_exps = sorted(
            self._data.items(),
            key=lambda x: (
                not x[1].deprecated,  # deprecated 的排前面（先删）
                x[1].success,
                x[1].hit_count,
                x[1].timestamp,
            ),
        )
        for eid, _ in sorted_exps[:len(self._data) - MAX_EXPERIENCES]:
            del self._data[eid]


# ── 轻量 TF-IDF 向量化（零外部依赖）──────────────────────────────

class _TfIdfIndex:
    """轻量 TF-IDF 索引，纯 Python 实现，用于经验检索精排"""

    def __init__(self):
        self._docs: dict[str, Counter] = {}  # exp_id -> term_freq
        self._idf: dict[str, float] = {}
        self._dirty = True

    def add(self, doc_id: str, text: str):
        """添加文档"""
        tokens = _extract_keywords(text)
        self._docs[doc_id] = Counter(tokens)
        self._dirty = True

    def remove(self, doc_id: str):
        """移除文档"""
        self._docs.pop(doc_id, None)
        self._dirty = True

    def _rebuild_idf(self):
        """重建 IDF"""
        if not self._dirty:
            return
        n = len(self._docs)
        if n == 0:
            self._idf = {}
            self._dirty = False
            return

        df: Counter = Counter()
        for tf in self._docs.values():
            for term in tf:
                df[term] += 1

        self._idf = {term: math.log(n / count) for term, count in df.items()}
        self._dirty = False

    def query(self, text: str, top_k: int = 5) -> list[tuple[str, float]]:
        """查询最相似的文档，返回 [(doc_id, score), ...]"""
        self._rebuild_idf()

        query_tokens = Counter(_extract_keywords(text))
        if not query_tokens:
            return []

        # query TF-IDF 向量
        q_vec = {t: tf * self._idf.get(t, 0) for t, tf in query_tokens.items()}
        q_norm = math.sqrt(sum(v * v for v in q_vec.values()))
        if q_norm == 0:
            return []

        scores = []
        for doc_id, doc_tf in self._docs.items():
            dot = sum(q_vec.get(t, 0) * tf * self._idf.get(t, 0) for t, tf in doc_tf.items())
            d_norm = math.sqrt(sum((tf * self._idf.get(t, 0)) ** 2 for t, tf in doc_tf.items()))
            if d_norm == 0:
                continue
            cosine = dot / (q_norm * d_norm)
            if cosine > 0.1:  # 最低阈值
                scores.append((doc_id, cosine))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
