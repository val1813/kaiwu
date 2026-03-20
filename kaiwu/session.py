"""会话管理 — 跨轮次任务状态持久化

Session 是开物"模型同权"的核心数据结构：
- 记录任务全程的决策锚点（anchors）
- 维护压缩后的历史摘要
- 保留最近 N 轮原文用于精确上下文
- 每次 MCP 工具调用时注入 ~800 token 的上下文

存储：~/.kaiwu/sessions/{session_id}.json（每个会话独立文件）
"""

import json
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from kaiwu.config import (
    SESSIONS_DIR,
    CONDENSE_KEEP_RECENT,
    MAX_INJECT_TOKENS,
)

# ── session_id 校验 ──────────────────────────────────────────────────
_SESSION_ID_RE = re.compile(r"^sess_\d{8}_[a-f0-9]{6}$")

# ── 列表上限 ─────────────────────────────────────────────────────────
MAX_ANCHORS = 30
MAX_COMPRESSED_HISTORY = 20
MAX_SUBTASKS = 50
MAX_CHECKPOINTS = 50


def _validate_session_id(session_id: str) -> bool:
    """校验 session_id 格式，防止路径穿越"""
    return bool(_SESSION_ID_RE.match(session_id))

# ── 数据模型 ────────────────────────────────────────────────────────

@dataclass
class Subtask:
    seq: int
    title: str
    depends_on: list[int] = field(default_factory=list)
    status: str = "pending"  # pending / in_progress / completed / failed


@dataclass
class Checkpoint:
    subtask_seq: int
    summary: str
    timestamp: float = 0.0
    success: bool = True

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class CompressedBlock:
    """一段被压缩的历史"""
    turn_range: str  # e.g. "1-18"
    summary: str
    compressed_at: float = 0.0

    def __post_init__(self):
        if self.compressed_at == 0.0:
            self.compressed_at = time.time()


@dataclass
class TurnRecord:
    """单轮操作记录"""
    turn: int
    action: str
    result: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class Session:
    session_id: str
    task: str
    anchors: list[str] = field(default_factory=list)
    subtasks: list[Subtask] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    project_summary: str = ""
    progress_summary: str = ""
    pending_issues: list[str] = field(default_factory=list)
    key_files: list[str] = field(default_factory=list)
    compressed_history: list[CompressedBlock] = field(default_factory=list)
    recent_turns: list[TurnRecord] = field(default_factory=list)
    turn_count: int = 0
    error_history: list[dict] = field(default_factory=list)  # [{error_type, fingerprint, timestamp}]
    created_at: float = 0.0
    updated_at: float = 0.0
    status: str = "active"  # active / completed / failed

    def __post_init__(self):
        now = time.time()
        if self.created_at == 0.0:
            self.created_at = now
        if self.updated_at == 0.0:
            self.updated_at = now


# ── Session 序列化/反序列化 ──────────────────────────────────────────

def _session_to_dict(s: Session) -> dict:
    """Session → JSON-safe dict"""
    return {
        "session_id": s.session_id,
        "task": s.task,
        "anchors": s.anchors,
        "subtasks": [asdict(st) for st in s.subtasks],
        "checkpoints": [asdict(cp) for cp in s.checkpoints],
        "project_summary": s.project_summary,
        "progress_summary": s.progress_summary,
        "pending_issues": s.pending_issues,
        "key_files": s.key_files,
        "compressed_history": [asdict(ch) for ch in s.compressed_history],
        "recent_turns": [asdict(rt) for rt in s.recent_turns],
        "turn_count": s.turn_count,
        "error_history": s.error_history,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "status": s.status,
    }


def _dict_to_session(d: dict) -> Session:
    """JSON dict → Session（兼容旧格式：缺少的字段用默认值）"""
    return Session(
        session_id=d["session_id"],
        task=d.get("task", ""),
        anchors=d.get("anchors", []),
        subtasks=[Subtask(**st) for st in d.get("subtasks", [])],
        checkpoints=[Checkpoint(**cp) for cp in d.get("checkpoints", [])],
        project_summary=d.get("project_summary", ""),
        progress_summary=d.get("progress_summary", ""),
        pending_issues=d.get("pending_issues", []),
        key_files=d.get("key_files", []),
        compressed_history=[CompressedBlock(**ch) for ch in d.get("compressed_history", [])],
        recent_turns=[TurnRecord(**rt) for rt in d.get("recent_turns", [])],
        turn_count=d.get("turn_count", 0),
        error_history=d.get("error_history", []),
        created_at=d.get("created_at", 0.0),
        updated_at=d.get("updated_at", 0.0),
        status=d.get("status", "active"),
    )


# ── SessionManager ──────────────────────────────────────────────────

class SessionManager:
    """会话管理器：创建、查找、更新、清理

    使用 filelock 防止并发写入（项目已有此依赖）。
    """

    def __init__(self):
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        if not _validate_session_id(session_id):
            raise ValueError(f"非法 session_id: {session_id!r}")
        return SESSIONS_DIR / f"{session_id}.json"

    def _lock_path(self, session_id: str) -> Path:
        if not _validate_session_id(session_id):
            raise ValueError(f"非法 session_id: {session_id!r}")
        return SESSIONS_DIR / f"{session_id}.lock"

    def _save(self, session: Session):
        session.updated_at = time.time()
        # 列表上限裁剪
        if len(session.anchors) > MAX_ANCHORS:
            session.anchors = session.anchors[-MAX_ANCHORS:]
        if len(session.compressed_history) > MAX_COMPRESSED_HISTORY:
            session.compressed_history = session.compressed_history[-MAX_COMPRESSED_HISTORY:]
        if len(session.subtasks) > MAX_SUBTASKS:
            session.subtasks = session.subtasks[-MAX_SUBTASKS:]
        if len(session.checkpoints) > MAX_CHECKPOINTS:
            session.checkpoints = session.checkpoints[-MAX_CHECKPOINTS:]

        from filelock import FileLock
        lock = FileLock(str(self._lock_path(session.session_id)), timeout=5)
        with lock:
            self._path(session.session_id).write_text(
                json.dumps(_session_to_dict(session), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _load(self, session_id: str) -> Optional[Session]:
        p = self._path(session_id)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return _dict_to_session(data)
        except Exception as e:
            logger.warning(f"加载会话失败 {session_id}: {e}")
            return None

    @staticmethod
    def _generate_session_id() -> str:
        """生成格式化 session_id: sess_{date}_{6chars}"""
        date_str = datetime.now().strftime("%Y%m%d")
        random_part = uuid.uuid4().hex[:6]
        return f"sess_{date_str}_{random_part}"

    # ── 核心 API ────────────────────────────────────────────────

    def create(self, task_goal: str, session_id: str = "") -> str:
        """创建新会话，返回 session_id"""
        if not session_id:
            session_id = self._generate_session_id()

        session = Session(session_id=session_id, task=task_goal)
        self._save(session)
        self._cleanup()

        logger.info(f"创建会话: {session_id}, 任务: {task_goal[:60]}")
        return session_id

    def create_session(self, task: str, session_id: str = "") -> Session:
        """创建新会话，返回 Session 对象（兼容旧 API）"""
        sid = self.create(task, session_id)
        return self._load(sid) or Session(session_id=sid, task=task)

    def get(self, session_id: str) -> Optional[dict]:
        """读取 session 原始 dict，不存在返回 None"""
        p = self._path(session_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def resolve_session(self, session_id: str = "") -> Optional[Session]:
        """解析会话：显式 ID 优先，否则找最近 2 小时内的活跃会话"""
        if session_id:
            return self._load(session_id)

        # 自动查找最近活跃会话
        now = time.time()
        two_hours = 2 * 3600
        best: Optional[Session] = None

        for p in SESSIONS_DIR.glob("*.json"):
            try:
                s = self._load(p.stem)
                if s and s.status == "active" and (now - s.updated_at) < two_hours:
                    if best is None or s.updated_at > best.updated_at:
                        best = s
            except Exception:
                continue

        if best:
            logger.debug(f"自动关联活跃会话: {best.session_id}")
        return best

    def update_anchors(self, session_id: str, anchors: list[str]) -> bool:
        """更新决策锚点（覆盖写入），按冒号前缀去重"""
        session = self._load(session_id)
        if not session:
            return False

        # 合并：新锚点按前缀替换旧的，保留不冲突的旧锚点
        merged: dict[str, str] = {}
        for a in session.anchors:
            prefix = a.split(":")[0].strip() if ":" in a else a
            merged[prefix] = a
        for a in anchors:
            prefix = a.split(":")[0].strip() if ":" in a else a
            merged[prefix] = a

        session.anchors = list(merged.values())
        self._save(session)
        return True

    def add_anchor(self, session_id: str, text: str):
        """添加单个决策锚点，按冒号前缀去重"""
        session = self._load(session_id)
        if not session:
            logger.warning(f"会话不存在: {session_id}")
            return

        prefix = text.split(":")[0].strip() if ":" in text else ""
        if prefix:
            session.anchors = [
                a for a in session.anchors
                if a.split(":")[0].strip() != prefix
            ]
        session.anchors.append(text)
        self._save(session)

    def append_turn(self, session_id: str, turn_data: dict) -> int:
        """追加一轮记录，返回当前总轮数"""
        session = self._load(session_id)
        if not session:
            return 0

        session.turn_count += 1
        record = TurnRecord(
            turn=session.turn_count,
            action=turn_data.get("action", ""),
            result=str(turn_data.get("result", ""))[:500],
        )
        session.recent_turns.append(record)

        # 只保留最近 N 轮原文
        keep = CONDENSE_KEEP_RECENT
        if len(session.recent_turns) > keep * 2:
            session.recent_turns = session.recent_turns[-keep:]

        self._save(session)
        return session.turn_count

    def apply_compression(self, session_id: str, summary: str, turn_range: str) -> bool:
        """将 turn_range 范围的历史替换为 summary，保留最近 N 轮"""
        session = self._load(session_id)
        if not session:
            return False

        block = CompressedBlock(turn_range=turn_range, summary=summary)
        session.compressed_history.append(block)

        # 更新 progress_summary
        session.progress_summary = summary

        # 只保留最近 N 轮原文
        keep = CONDENSE_KEEP_RECENT
        if len(session.recent_turns) > keep:
            session.recent_turns = session.recent_turns[-keep:]

        self._save(session)
        logger.info(f"会话 {session_id} 已压缩 turns {turn_range}")
        return True

    def set_subtasks(self, session_id: str, subtasks: list[Subtask]):
        """设置子任务列表（首次规划时调用）"""
        session = self._load(session_id)
        if not session:
            return
        if not session.subtasks:
            session.subtasks = subtasks
            self._save(session)
            logger.info(f"会话 {session_id} 设置 {len(subtasks)} 个子任务")

    def add_checkpoint(self, session_id: str, subtask_seq: int, summary: str):
        """记录检查点并标记对应子任务完成"""
        session = self._load(session_id)
        if not session:
            return

        cp = Checkpoint(subtask_seq=subtask_seq, summary=summary)
        session.checkpoints.append(cp)

        for st in session.subtasks:
            if st.seq == subtask_seq:
                st.status = "completed"
                break

        self._save(session)
        logger.info(f"会话 {session_id} 检查点: 子任务 {subtask_seq} 完成")

    def complete_session(self, session_id: str, success: bool = True):
        """标记会话结束"""
        session = self._load(session_id)
        if not session:
            return
        session.status = "completed" if success else "failed"
        self._save(session)
        logger.info(f"会话 {session_id} 已标记为 {session.status}")

    def record_error(self, session_id: str, error_type: str, fingerprint: str = ""):
        """记录一次错误到会话的 error_history（用于循环检测）

        Args:
            session_id: 会话 ID
            error_type: 错误类型摘要（如 "UnicodeDecodeError"）
            fingerprint: 错误指纹（可选，来自 ErrorKB）
        """
        session = self._load(session_id)
        if not session:
            return
        session.error_history.append({
            "error_type": error_type[:100],
            "fingerprint": fingerprint[:32],
            "timestamp": time.time(),
        })
        # 只保留最近 20 条错误记录
        session.error_history = session.error_history[-20:]
        self._save(session)

    def get_error_stats(self, session_id: str, window: int = 2) -> dict:
        """分析会话内的错误模式，检测循环

        Args:
            session_id: 会话 ID
            window: 检测窗口大小（最近 N 条错误，默认 2 更早发现循环）

        Returns:
            {
                "error_count": int,        # 总错误次数
                "is_looping": bool,        # 是否陷入循环
                "loop_type": str,          # 错误类型（如果循环）
                "consecutive": int,        # 连续同类错误次数
                "suggestion": str          # 建议（如果循环）
            }
        """
        session = self._load(session_id)
        if not session or not session.error_history:
            return {"error_count": 0, "is_looping": False, "consecutive": 0}

        total = len(session.error_history)
        recent = session.error_history[-window:]

        # 检测连续同类错误（按 fingerprint 或 error_type）
        if len(recent) >= window:
            fps = [e.get("fingerprint", "") for e in recent]
            types = [e.get("error_type", "") for e in recent]

            # 优先用 fingerprint 判断（更精确）
            if fps[0] and all(f == fps[0] for f in fps):
                return {
                    "error_count": total,
                    "is_looping": True,
                    "loop_type": types[-1],
                    "consecutive": window,
                    "suggestion": _build_loop_suggestion(types[-1], window),
                }

            # 退而用 error_type 前缀判断
            type_prefixes = [t.split(":")[0].strip() for t in types]
            if type_prefixes[0] and all(p == type_prefixes[0] for p in type_prefixes):
                return {
                    "error_count": total,
                    "is_looping": True,
                    "loop_type": types[-1],
                    "consecutive": window,
                    "suggestion": _build_loop_suggestion(type_prefixes[0], window),
                }

        return {"error_count": total, "is_looping": False, "consecutive": 0}

    def update_project_summary(self, session_id: str, summary: str):
        """更新项目摘要"""
        session = self._load(session_id)
        if not session:
            return
        session.project_summary = summary
        self._save(session)

    def update_progress(self, session_id: str, progress: str = "",
                        pending: list[str] | None = None,
                        key_files: list[str] | None = None):
        """更新进度摘要、待处理事项、关键文件"""
        session = self._load(session_id)
        if not session:
            return
        if progress:
            session.progress_summary = progress
        if pending is not None:
            session.pending_issues = pending
        if key_files is not None:
            session.key_files = key_files
        self._save(session)

    def get_context_for_injection(self, session_id: str) -> str:
        """生成适合注入 LLM 的上下文字符串，控制在 MAX_INJECT_TOKENS 内

        格式：
        [任务目标] xxx
        [决策锚点] 框架: FastAPI | 数据库: SQLite | ...
        [当前进度] xxx
        [待处理] xxx
        [历史摘要] xxx（如有）
        [用户画像] xxx（如有，自动注入）
        [最近操作] turn N: xxx
        """
        session = self._load(session_id)
        if not session:
            return ""
        ctx = build_session_context(session, max_chars=MAX_INJECT_TOKENS * 3)

        # 注入用户画像（如果有）
        try:
            from kaiwu.profile import get_profile_context
            profile_ctx = get_profile_context(max_chars=200)
            if profile_ctx:
                ctx += f"\n{profile_ctx}"
        except Exception:
            pass

        return ctx

    def list_sessions(self, limit: int = 10) -> list[dict]:
        """列出最近的 session，用于 CLI 展示"""
        sessions: list[dict] = []
        for p in sorted(SESSIONS_DIR.glob("*.json"),
                        key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id", p.stem),
                    "task": data.get("task", "")[:60],
                    "turn_count": data.get("turn_count", 0),
                    "status": data.get("status", "unknown"),
                    "created_at": data.get("created_at", 0),
                    "updated_at": data.get("updated_at", 0),
                })
            except Exception:
                continue
            if len(sessions) >= limit:
                break
        return sessions

    def delete(self, session_id: str) -> bool:
        """删除 session 文件"""
        p = self._path(session_id)
        if p.exists():
            p.unlink()
            # 清理 lock 文件
            lock_p = self._lock_path(session_id)
            if lock_p.exists():
                try:
                    lock_p.unlink()
                except Exception:
                    pass
            logger.info(f"已删除会话: {session_id}")
            return True
        return False

    def _cleanup(self):
        """自动清理：7 天过期删除，最多保留 20 个会话"""
        try:
            now = time.time()
            seven_days = 7 * 24 * 3600
            files = sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)

            for p in files:
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    updated = data.get("updated_at", 0)
                    if (now - updated) > seven_days:
                        p.unlink()
                        logger.debug(f"清理过期会话: {p.stem}")
                except Exception:
                    continue

            files = sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
            if len(files) > 20:
                for p in files[:-20]:
                    try:
                        p.unlink()
                        logger.debug(f"清理多余会话: {p.stem}")
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"会话清理失败（不影响主流程）: {e}")


# ── 循环检测建议生成 ───────────────────────────────────────────────

_LOOP_SUGGESTIONS: dict[str, str] = {
    "ModuleNotFoundError": "模块缺失循环：1) 确认是否在正确的 venv/conda 环境中 2) 检查 pip install 的包名是否正确（如 Pillow 而非 PIL）3) 如果是系统包，检查 PATH",
    "ImportError": "导入错误循环：1) 检查循环导入 2) 确认包版本兼容性 3) 尝试相对导入或延迟导入",
    "TypeError": "类型错误循环：1) 打印实际类型确认 2) 检查函数签名是否变更 3) 可能是 None 值未处理",
    "AttributeError": "属性错误循环：1) 确认对象类型是否正确 2) 检查拼写 3) 可能是版本 API 变更",
    "FileNotFoundError": "文件路径循环：1) 用 Path.resolve() 打印绝对路径 2) 检查 CWD 3) Windows 注意反斜杠转义",
    "UnicodeDecodeError": "编码错误循环：1) 统一用 encoding='utf-8' 2) 加 errors='replace' 3) Windows 默认 GBK，需显式指定",
    "UnicodeEncodeError": "编码输出循环：1) sys.stdout.reconfigure(encoding='utf-8') 2) 避免 emoji，用 [OK][FAIL] 替代",
    "SyntaxError": "语法错误循环：1) 检查 Python 版本兼容性 2) 检查缩进混用空格/tab 3) f-string 中的引号嵌套",
    "ConnectionError": "连接错误循环：1) 检查目标服务是否启动 2) 检查端口是否被占用 3) 检查防火墙/代理设置",
    "npm ERR": "npm 错误循环：1) 删除 node_modules 和 lock 文件重装 2) 检查 Node 版本 3) 换淘宝镜像源",
}


def _build_loop_suggestion(error_type: str, consecutive: int) -> str:
    """根据错误类型生成针对性的循环检测建议"""
    # 尝试精确匹配
    for key, suggestion in _LOOP_SUGGESTIONS.items():
        if key.lower() in error_type.lower():
            return (
                f"[循环警告] 连续 {consecutive} 次同类错误（{error_type[:50]}）。"
                f"{suggestion}"
            )

    # 通用建议
    return (
        f"[循环警告] 连续 {consecutive} 次同类错误（{error_type[:50]}）。"
        "当前修复路径无效，建议：1) 调用 kaiwu_plan 重新规划 "
        "2) 完全换一种实现方案 3) 先读取相关源码确认根本原因 "
        "4) 检查是否有前置依赖未满足"
    )


# ── 上下文构建 ──────────────────────────────────────────────────────

def build_session_context(session: Session, max_chars: int = 2400) -> str:
    """将会话数据压缩为注入文本

    输出格式：
    [任务目标] xxx
    [决策锚点] A | B | C
    [当前进度] xxx
    [待处理] xxx
    [历史摘要] xxx
    [项目结构] xxx
    [步骤进度] ...
    [最近操作] turn N: action → result

    超出限制时渐进截断：先缩项目结构，再减历史摘要，再减最近操作。
    锚点和进度永不截断。
    """
    parts: list[str] = []

    # ── 任务目标（永不截断）──
    parts.append(f"[任务目标] {session.task[:120]}")

    # ── 决策锚点（永不截断）──
    if session.anchors:
        parts.append(f"[决策锚点] {' | '.join(session.anchors)}")

    # ── 当前进度（永不截断）──
    if session.progress_summary:
        parts.append(f"[当前进度] {session.progress_summary[:200]}")

    # ── 待处理 ──
    if session.pending_issues:
        issues_text = "; ".join(session.pending_issues[:5])
        parts.append(f"[待处理] {issues_text}")

    # ── 历史摘要 ──
    if session.compressed_history:
        latest = session.compressed_history[-1]
        parts.append(f"[历史摘要 turns {latest.turn_range}] {latest.summary[:300]}")

    # ── 步骤进度 ──
    completed_subs = [st for st in session.subtasks if st.status == "completed"]
    pending_subs = [st for st in session.subtasks if st.status in ("pending", "in_progress")]
    if completed_subs or pending_subs:
        progress_lines: list[str] = []
        for st in completed_subs:
            cp_summary = ""
            for cp in session.checkpoints:
                if cp.subtask_seq == st.seq:
                    cp_summary = cp.summary
            suffix = f" — {cp_summary}" if cp_summary else ""
            progress_lines.append(f"  {st.seq}. [OK] {st.title}{suffix}")
        for st in pending_subs:
            marker = ">>>" if st.status == "in_progress" else "   "
            progress_lines.append(f"  {marker} {st.seq}. {st.title}")
        parts.append("[步骤进度]\n" + "\n".join(progress_lines))

    # ── 项目结构（可截断）──
    if session.project_summary:
        parts.append(f"[项目结构]\n{session.project_summary}")

    # ── 最近操作（可截断）──
    if session.recent_turns:
        recent_lines = []
        for rt in session.recent_turns[-5:]:
            result_text = f" -> {rt.result[:60]}" if rt.result else ""
            recent_lines.append(f"  turn {rt.turn}: {rt.action[:80]}{result_text}")
        parts.append("[最近操作]\n" + "\n".join(recent_lines))

    text = "\n".join(parts)

    # ── 渐进截断 ──
    if len(text) > max_chars:
        text = _truncate_context(session, max_chars)

    return text


def _truncate_context(session: Session, max_chars: int) -> str:
    """渐进截断：锚点和进度永不截断"""
    parts: list[str] = []

    # 不可截断部分
    parts.append(f"[任务目标] {session.task[:80]}")
    if session.anchors:
        anchors_text = " | ".join(a[:50] for a in session.anchors[-8:])
        parts.append(f"[决策锚点] {anchors_text}")
    if session.progress_summary:
        parts.append(f"[当前进度] {session.progress_summary[:150]}")
    if session.pending_issues:
        issues_text = "; ".join(session.pending_issues[:3])
        parts.append(f"[待处理] {issues_text[:100]}")

    # 可截断部分 — 按优先级逐步添加
    remaining = max_chars - len("\n".join(parts))

    # 历史摘要（优先级高）
    if session.compressed_history and remaining > 200:
        latest = session.compressed_history[-1]
        summary_text = f"[历史摘要] {latest.summary[:min(200, remaining - 50)]}"
        parts.append(summary_text)
        remaining -= len(summary_text)

    # 步骤进度（优先级中）
    completed_subs = [st for st in session.subtasks if st.status == "completed"]
    pending_subs = [st for st in session.subtasks if st.status in ("pending", "in_progress")]
    if (completed_subs or pending_subs) and remaining > 150:
        progress_lines: list[str] = ["[步骤进度]"]
        for st in completed_subs[-5:]:
            progress_lines.append(f"  {st.seq}. [OK] {st.title[:40]}")
        for st in pending_subs[:3]:
            marker = ">>>" if st.status == "in_progress" else "   "
            progress_lines.append(f"  {marker} {st.seq}. {st.title[:40]}")
        progress_text = "\n".join(progress_lines)
        if len(progress_text) < remaining:
            parts.append(progress_text)
            remaining -= len(progress_text)

    # 项目结构（优先级低）
    if session.project_summary and remaining > 100:
        proj = session.project_summary[:min(150, remaining - 20)]
        parts.append(f"[项目结构]\n{proj}")
        remaining -= len(proj) + 15

    # 最近操作（优先级最低）
    if session.recent_turns and remaining > 100:
        recent_lines = ["[最近操作]"]
        for rt in session.recent_turns[-3:]:
            line = f"  turn {rt.turn}: {rt.action[:50]}"
            recent_lines.append(line)
        recent_text = "\n".join(recent_lines)
        if len(recent_text) < remaining:
            parts.append(recent_text)

    text = "\n".join(parts)

    # 最终硬截断
    if len(text) > max_chars:
        text = text[:max_chars - 3] + "..."

    return text
