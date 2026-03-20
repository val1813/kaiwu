"""用户记忆系统 — 跨会话持久记忆，让主AI像长期同事一样了解用户

核心思路：
- 在 kaiwu_record 成功时，自动从任务描述中提取值得记忆的信息
- 在 kaiwu_plan 时，自动注入与当前任务相关的记忆
- 记忆按项目隔离 + 全局记忆（project_name="" 的记忆所有项目可见）
- 记忆有 hit_count 和 last_hit 追踪，长期不命中的记忆可清理
- 提取用 DeepSeek 异步执行，不阻塞主流程

存储在 ~/.kaiwu/memory.json

记忆分类：
1. project_convention — 项目约定（目录结构、API前缀、部署流程）
2. user_preference   — 用户偏好（编码风格、工具选择、语言习惯）
3. tech_stack        — 技术栈（框架版本、数据库选型、依赖关系）
4. pitfall           — 踩过的坑（环境问题、兼容性、配置陷阱）
5. workflow          — 常用工作流（构建命令、测试流程、部署步骤）
"""

import json
import threading
import time
import hashlib
from pathlib import Path
from typing import Optional

from loguru import logger

from kaiwu.config import MEMORY_PATH, DEFAULT_TIMEOUT


# ── 记忆提取提示词 ────────────────────────────────────────────────

_EXTRACT_SYSTEM = """\
你是一位编程助手记忆提取器。
给你一个刚完成的编程任务信息，提取出值得跨会话记住的信息。

# 什么值得记忆

1. 项目约定：目录结构规则、API命名规范、部署流程、分支策略
2. 用户偏好：喜欢的框架/工具、编码风格、语言偏好
3. 技术栈：项目用了什么技术、版本约束、依赖关系
4. 踩过的坑：环境问题、兼容性坑、配置陷阱及解决方法
5. 常用工作流：构建命令、测试流程、部署步骤

# 什么不值得记忆

- 一次性的bug修复细节（已有经验库记录）
- 具体的代码片段（太细节）
- 临时的调试过程
- 通用编程知识（主AI已经知道）

# 输出格式

严格返回 JSON 数组，每条记忆一个对象：
```json
[
  {
    "category": "project_convention|user_preference|tech_stack|pitfall|workflow",
    "content": "一句话描述（不超过80字）",
    "project_specific": true
  }
]
```

如果没有值得记忆的信息，返回空数组 []。

# 规则

1. 每条 content 不超过 80 字，突出关键信息
2. project_specific=true 表示仅对当前项目有效，false 表示全局通用
3. 最多提取 3 条记忆
4. 不要重复已有记忆中的内容
5. 只输出 JSON，不要其他文字
"""


# ── 记忆条目 ──────────────────────────────────────────────────────

class MemoryEntry:
    """单条记忆"""

    def __init__(
        self,
        memory_id: str,
        category: str,
        content: str,
        project_name: str = "",
        created_at: float = 0,
        hit_count: int = 0,
        last_hit: float = 0,
    ):
        self.memory_id = memory_id
        self.category = category
        self.content = content
        self.project_name = project_name
        self.created_at = created_at or time.time()
        self.hit_count = hit_count
        self.last_hit = last_hit

    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "category": self.category,
            "content": self.content,
            "project_name": self.project_name,
            "created_at": self.created_at,
            "hit_count": self.hit_count,
            "last_hit": self.last_hit,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        return cls(
            memory_id=d.get("memory_id", ""),
            category=d.get("category", ""),
            content=d.get("content", ""),
            project_name=d.get("project_name", ""),
            created_at=d.get("created_at", 0),
            hit_count=d.get("hit_count", 0),
            last_hit=d.get("last_hit", 0),
        )


# ── 中文分词辅助 ──────────────────────────────────────────────────

import re

_CN_CHAR = re.compile(r'[\u4e00-\u9fff]')


def _extract_cn_grams(text: str, n: int = 2) -> set[str]:
    """从文本中提取中文 n-gram（默认 bigram）

    例: "部署前端" → {"部署", "署前", "前端"}
    只提取连续中文字符的 n-gram，跳过非中文字符。
    """
    grams: set[str] = set()
    # 提取连续中文片段
    cn_spans = re.findall(r'[\u4e00-\u9fff]+', text)
    for span in cn_spans:
        for i in range(len(span) - n + 1):
            grams.add(span[i:i + n])
    return grams


# ── 记忆存储 ──────────────────────────────────────────────────────

class MemoryStore:
    """记忆存储引擎"""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or MEMORY_PATH
        self._data: dict[str, dict] = self._load()
        self._lock = threading.Lock()

    def _load(self) -> dict[str, dict]:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return raw
            except Exception:
                pass
        return {}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"保存记忆失败: {e}")

    @staticmethod
    def _make_id(content: str, project_name: str) -> str:
        """基于内容生成去重ID"""
        raw = f"{project_name}:{content}".lower().strip()
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

    def add(self, category: str, content: str, project_name: str = "") -> Optional[str]:
        """添加一条记忆，自动去重

        Returns:
            memory_id 或 None（重复时）
        """
        content = content.strip()
        if not content or len(content) < 5:
            return None

        mid = self._make_id(content, project_name)

        with self._lock:
            # 去重：完全相同的记忆不重复存
            if mid in self._data:
                # 已存在，更新 hit_count
                self._data[mid]["hit_count"] = self._data[mid].get("hit_count", 0) + 1
                self._data[mid]["last_hit"] = time.time()
                self._save()
                return None

            # 相似度去重：同项目同类别下，内容高度相似的跳过
            for existing in self._data.values():
                if (existing.get("project_name", "") == project_name
                        and existing.get("category", "") == category
                        and self._is_similar(content, existing.get("content", ""))):
                    logger.debug(f"记忆相似，跳过: {content[:40]}")
                    return None

            entry = MemoryEntry(
                memory_id=mid,
                category=category,
                content=content,
                project_name=project_name,
            )
            self._data[mid] = entry.to_dict()
            self._save()
            logger.info(f"新记忆已存储: [{category}] {content[:50]} (project={project_name or '全局'})")
            return mid

    @staticmethod
    def _is_similar(a: str, b: str) -> bool:
        """简单的相似度判断：关键词+中文2-gram 重叠率 > 0.7"""
        tokens_a = set(a.lower().split()) | _extract_cn_grams(a.lower())
        tokens_b = set(b.lower().split()) | _extract_cn_grams(b.lower())
        if not tokens_a or not tokens_b:
            return False
        overlap = len(tokens_a & tokens_b)
        return overlap / min(len(tokens_a), len(tokens_b)) > 0.7

    def query(self, task: str, project_name: str = "",
              limit: int = 5, max_chars: int = 500) -> str:
        """查询与任务相关的记忆，返回注入文本

        匹配逻辑：
        1. 全局记忆（project_name=""）始终参与
        2. 同项目记忆优先
        3. 按关键词相关度排序
        4. 命中时更新 hit_count
        """
        if not self._data:
            return ""

        task_lower = task.lower()
        task_tokens = set(task_lower.split())
        # 提取中文 2-gram（解决中文无空格分词问题）
        task_cn_grams = _extract_cn_grams(task_lower)
        candidates: list[tuple[float, dict]] = []

        for entry in self._data.values():
            ep = entry.get("project_name", "")
            # 只看全局记忆 + 同项目记忆
            if ep and ep != project_name:
                continue

            content = entry.get("content", "").lower()
            content_tokens = set(content.split())
            content_cn_grams = _extract_cn_grams(content)

            # 英文关键词重叠
            overlap = len(task_tokens & content_tokens)
            # 中文 2-gram 重叠
            cn_overlap = len(task_cn_grams & content_cn_grams)

            base_score = overlap + cn_overlap * 1.0
            # 必须有关键词命中才算候选，否则跳过
            if base_score <= 0:
                continue

            score = base_score
            # 同项目加分（仅在已有命中基础上）
            if ep == project_name and project_name:
                score += 2
            # hit_count 加分（越常用越重要）
            score += min(entry.get("hit_count", 0), 5) * 0.3

            candidates.append((score, entry))

        if not candidates:
            return ""

        # 按分数排序
        candidates.sort(key=lambda x: -x[0])
        selected = candidates[:limit]

        # 更新 hit_count
        now = time.time()
        with self._lock:
            for _, entry in selected:
                mid = entry.get("memory_id", "")
                if mid in self._data:
                    self._data[mid]["hit_count"] = self._data[mid].get("hit_count", 0) + 1
                    self._data[mid]["last_hit"] = now
            self._save()

        # 组装注入文本
        lines: list[str] = []
        total_len = 0
        for _, entry in selected:
            cat = entry.get("category", "")
            content = entry.get("content", "")
            line = f"- [{cat}] {content}"
            if total_len + len(line) > max_chars:
                break
            lines.append(line)
            total_len += len(line)

        return "\n".join(lines)

    def get_all(self) -> list[dict]:
        """返回所有记忆（供 CLI 展示）"""
        return list(self._data.values())

    def remove(self, memory_id: str) -> bool:
        """删除一条记忆"""
        with self._lock:
            if memory_id in self._data:
                del self._data[memory_id]
                self._save()
                return True
        return False

    def cleanup(self, max_age_days: int = 90, min_hits: int = 0) -> int:
        """清理过期记忆

        删除条件：创建超过 max_age_days 天 且 hit_count <= min_hits
        """
        cutoff = time.time() - max_age_days * 86400
        to_remove = []
        for mid, entry in self._data.items():
            if entry.get("created_at", 0) < cutoff and entry.get("hit_count", 0) <= min_hits:
                to_remove.append(mid)

        with self._lock:
            for mid in to_remove:
                del self._data[mid]
            if to_remove:
                self._save()

        if to_remove:
            logger.info(f"清理了 {len(to_remove)} 条过期记忆")
        return len(to_remove)


# ── 全局单例 ──────────────────────────────────────────────────────

_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


# ── 异步记忆提取 ──────────────────────────────────────────────────

def extract_memories_async(
    task: str,
    project_name: str = "",
    existing_memories: str = "",
):
    """后台线程：调用 DeepSeek 从任务中提取记忆

    Args:
        task: 完成的任务描述
        project_name: 项目名
        existing_memories: 已有记忆文本（避免重复提取）
    """
    def _worker():
        try:
            _extract_and_store(task, project_name, existing_memories)
        except Exception as e:
            logger.debug(f"异步记忆提取失败（静默）: {e}")

    t = threading.Thread(target=_worker, daemon=True, name="memory-extract")
    t.start()


def _extract_and_store(
    task: str,
    project_name: str = "",
    existing_memories: str = "",
):
    """调用 DeepSeek 提取记忆并存储"""
    from kaiwu.llm_client import call_llm
    from kaiwu.quota import check_quota, record_call

    allowed, _ = check_quota()
    if not allowed:
        return

    # 任务太短，不值得提取
    if len(task.strip()) < 30:
        return

    user_parts = [f"# 刚完成的任务\n\n{task[:500]}"]
    if project_name:
        user_parts.append(f"\n# 项目: {project_name}")
    if existing_memories:
        user_parts.append(f"\n# 已有记忆（不要重复）\n\n{existing_memories}")

    try:
        raw = call_llm(
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": "\n".join(user_parts)},
            ],
            max_tokens=300,
            temperature=0.3,
            timeout=DEFAULT_TIMEOUT,
            purpose="memory",
        )
        record_call()

        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        memories = json.loads(text)
        if not isinstance(memories, list):
            return

        store = get_memory_store()
        added = 0
        for mem in memories[:3]:
            if not isinstance(mem, dict):
                continue
            category = mem.get("category", "")
            content = mem.get("content", "")
            project_specific = mem.get("project_specific", True)

            if not category or not content:
                continue

            actual_project = project_name if project_specific else ""
            mid = store.add(category, content, actual_project)
            if mid:
                added += 1

        if added:
            logger.info(f"自动提取了 {added} 条新记忆 (project={project_name or '全局'})")

    except json.JSONDecodeError:
        logger.debug("记忆提取返回非 JSON，跳过")
    except Exception as e:
        logger.debug(f"记忆提取 LLM 调用失败: {e}")


# ── 便捷函数 ──────────────────────────────────────────────────────

def inject_memory_context(task: str, project_name: str = "",
                          max_chars: int = 500) -> str:
    """便捷函数：查询相关记忆，返回注入文本（planner/server 调用）"""
    try:
        store = get_memory_store()
        return store.query(task, project_name=project_name, max_chars=max_chars)
    except Exception:
        return ""


def trigger_memory_extraction(task: str, project_name: str = ""):
    """便捷函数：触发异步记忆提取（recorder 调用）"""
    try:
        store = get_memory_store()
        existing = store.query(task, project_name=project_name, max_chars=300)
        extract_memories_async(task, project_name, existing)
    except Exception as e:
        logger.debug(f"触发记忆提取失败（静默）: {e}")
