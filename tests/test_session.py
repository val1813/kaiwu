"""会话管理模块单元测试"""

import json
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import kaiwu.config
from kaiwu.session import (
    _validate_session_id,
    SessionManager,
    Session,
    Subtask,
    Checkpoint,
    CompressedBlock,
    TurnRecord,
    build_session_context,
    _build_loop_suggestion,
    MAX_ANCHORS,
    MAX_COMPRESSED_HISTORY,
    MAX_SUBTASKS,
    MAX_CHECKPOINTS,
)


# ── fixtures ──────────────────────────────────────────────────────────

VALID_SID = "sess_20260320_ab12cd"


@pytest.fixture
def sessions_dir(tmp_path, monkeypatch):
    """将 SESSIONS_DIR 重定向到 tmp_path，隔离真实文件系统"""
    d = tmp_path / "sessions"
    d.mkdir()
    monkeypatch.setattr(kaiwu.config, "SESSIONS_DIR", d)
    # session.py 在模块级 import 了 SESSIONS_DIR，需同步 patch
    import kaiwu.session as sm
    monkeypatch.setattr(sm, "SESSIONS_DIR", d)
    return d


@pytest.fixture
def mgr(sessions_dir):
    """返回指向 tmp sessions_dir 的 SessionManager"""
    return SessionManager()


@pytest.fixture
def created_sid(mgr):
    """创建一个真实会话，返回 session_id"""
    return mgr.create("测试任务")


# ── _validate_session_id ──────────────────────────────────────────────

class TestValidateSessionId:
    def test_valid(self):
        assert _validate_session_id("sess_20260320_ab12cd") is True

    def test_valid_all_digits_hex(self):
        assert _validate_session_id("sess_20991231_000000") is True

    def test_empty_string(self):
        assert _validate_session_id("") is False

    def test_wrong_prefix(self):
        assert _validate_session_id("session_20260320_ab12cd") is False

    def test_date_too_short(self):
        assert _validate_session_id("sess_2026032_ab12cd") is False

    def test_hex_too_short(self):
        assert _validate_session_id("sess_20260320_ab12c") is False

    def test_hex_too_long(self):
        assert _validate_session_id("sess_20260320_ab12cde") is False

    def test_uppercase_hex_rejected(self):
        # regex uses [a-f0-9], uppercase not allowed
        assert _validate_session_id("sess_20260320_AB12CD") is False

    def test_path_traversal_dotdot(self):
        assert _validate_session_id("../../../etc/passwd") is False

    def test_path_traversal_embedded(self):
        assert _validate_session_id("sess_20260320_ab12cd/../evil") is False

    def test_null_bytes(self):
        assert _validate_session_id("sess_20260320_ab12cd\x00") is False

    def test_spaces(self):
        assert _validate_session_id("sess_20260320_ab 12c") is False


# ── SessionManager._path / _lock_path ────────────────────────────────

class TestManagerPaths:
    def test_path_valid(self, mgr, sessions_dir):
        p = mgr._path(VALID_SID)
        assert p == sessions_dir / f"{VALID_SID}.json"

    def test_lock_path_valid(self, mgr, sessions_dir):
        p = mgr._lock_path(VALID_SID)
        assert p == sessions_dir / f"{VALID_SID}.lock"

    def test_path_invalid_raises(self, mgr):
        with pytest.raises(ValueError, match="非法 session_id"):
            mgr._path("../evil")

    def test_lock_path_invalid_raises(self, mgr):
        with pytest.raises(ValueError, match="非法 session_id"):
            mgr._lock_path("")

    def test_path_traversal_raises(self, mgr):
        with pytest.raises(ValueError):
            mgr._path("sess_20260320_ab12cd/../other")


# ── SessionManager.create ─────────────────────────────────────────────

class TestManagerCreate:
    def test_returns_valid_session_id(self, mgr):
        sid = mgr.create("build a web app")
        assert _validate_session_id(sid)

    def test_creates_json_file(self, mgr, sessions_dir):
        sid = mgr.create("build a web app")
        assert (sessions_dir / f"{sid}.json").exists()

    def test_file_contains_task(self, mgr, sessions_dir):
        sid = mgr.create("my special task")
        data = json.loads((sessions_dir / f"{sid}.json").read_text(encoding="utf-8"))
        assert data["task"] == "my special task"

    def test_file_status_active(self, mgr, sessions_dir):
        sid = mgr.create("task")
        data = json.loads((sessions_dir / f"{sid}.json").read_text(encoding="utf-8"))
        assert data["status"] == "active"

    def test_explicit_session_id(self, mgr, sessions_dir):
        sid = mgr.create("task", session_id=VALID_SID)
        assert sid == VALID_SID
        assert (sessions_dir / f"{VALID_SID}.json").exists()

    def test_two_creates_different_ids(self, mgr):
        sid1 = mgr.create("task A")
        sid2 = mgr.create("task B")
        assert sid1 != sid2


# ── SessionManager._save (list caps) ─────────────────────────────────

class TestManagerSaveCaps:
    def _make_session(self, sid=VALID_SID, task="t"):
        return Session(session_id=sid, task=task)

    def test_anchors_capped(self, mgr, sessions_dir):
        s = self._make_session()
        s.anchors = [f"anchor_{i}" for i in range(MAX_ANCHORS + 10)]
        mgr._save(s)
        loaded = mgr._load(VALID_SID)
        assert len(loaded.anchors) == MAX_ANCHORS
        # keeps the tail
        assert loaded.anchors[-1] == f"anchor_{MAX_ANCHORS + 9}"

    def test_compressed_history_capped(self, mgr, sessions_dir):
        s = self._make_session()
        s.compressed_history = [
            CompressedBlock(turn_range=f"{i}-{i+1}", summary=f"s{i}")
            for i in range(MAX_COMPRESSED_HISTORY + 5)
        ]
        mgr._save(s)
        loaded = mgr._load(VALID_SID)
        assert len(loaded.compressed_history) == MAX_COMPRESSED_HISTORY

    def test_subtasks_capped(self, mgr, sessions_dir):
        s = self._make_session()
        s.subtasks = [Subtask(seq=i, title=f"task {i}") for i in range(MAX_SUBTASKS + 5)]
        mgr._save(s)
        loaded = mgr._load(VALID_SID)
        assert len(loaded.subtasks) == MAX_SUBTASKS

    def test_checkpoints_capped(self, mgr, sessions_dir):
        s = self._make_session()
        s.checkpoints = [
            Checkpoint(subtask_seq=i, summary=f"cp {i}")
            for i in range(MAX_CHECKPOINTS + 5)
        ]
        mgr._save(s)
        loaded = mgr._load(VALID_SID)
        assert len(loaded.checkpoints) == MAX_CHECKPOINTS

    def test_within_limits_unchanged(self, mgr, sessions_dir):
        s = self._make_session()
        s.anchors = ["a", "b", "c"]
        mgr._save(s)
        loaded = mgr._load(VALID_SID)
        assert loaded.anchors == ["a", "b", "c"]

    def test_updated_at_set_on_save(self, mgr, sessions_dir):
        s = self._make_session()
        before = time.time()
        mgr._save(s)
        after = time.time()
        loaded = mgr._load(VALID_SID)
        assert before <= loaded.updated_at <= after


# ── SessionManager._load ──────────────────────────────────────────────

class TestManagerLoad:
    def test_load_existing(self, mgr, created_sid):
        session = mgr._load(created_sid)
        assert session is not None
        assert session.session_id == created_sid

    def test_load_missing_returns_none(self, mgr):
        result = mgr._load(VALID_SID)
        assert result is None

    def test_load_preserves_task(self, mgr, sessions_dir):
        mgr.create("preserve this task", session_id=VALID_SID)
        session = mgr._load(VALID_SID)
        assert session.task == "preserve this task"

    def test_load_corrupt_json_returns_none(self, mgr, sessions_dir):
        (sessions_dir / f"{VALID_SID}.json").write_text("not json", encoding="utf-8")
        result = mgr._load(VALID_SID)
        assert result is None

    def test_load_roundtrip_anchors(self, mgr, sessions_dir):
        mgr.create("task", session_id=VALID_SID)
        mgr.update_anchors(VALID_SID, ["框架: FastAPI", "数据库: SQLite"])
        session = mgr._load(VALID_SID)
        assert "框架: FastAPI" in session.anchors
        assert "数据库: SQLite" in session.anchors


# ── SessionManager.record_error ──────────────────────────────────────

class TestRecordError:
    def test_records_error(self, mgr, created_sid):
        mgr.record_error(created_sid, "UnicodeDecodeError", "fp_abc123")
        session = mgr._load(created_sid)
        assert len(session.error_history) == 1
        assert session.error_history[0]["error_type"] == "UnicodeDecodeError"
        assert session.error_history[0]["fingerprint"] == "fp_abc123"

    def test_caps_at_20(self, mgr, created_sid):
        for i in range(25):
            mgr.record_error(created_sid, f"Error_{i}", f"fp_{i:06x}")
        session = mgr._load(created_sid)
        assert len(session.error_history) == 20
        # keeps the most recent 20
        assert session.error_history[-1]["error_type"] == "Error_24"

    def test_error_type_truncated_at_100(self, mgr, created_sid):
        long_type = "E" * 150
        mgr.record_error(created_sid, long_type)
        session = mgr._load(created_sid)
        assert len(session.error_history[0]["error_type"]) == 100

    def test_fingerprint_truncated_at_32(self, mgr, created_sid):
        long_fp = "a" * 50
        mgr.record_error(created_sid, "SomeError", long_fp)
        session = mgr._load(created_sid)
        assert len(session.error_history[0]["fingerprint"]) == 32

    def test_missing_session_no_crash(self, mgr):
        # should silently return, not raise
        mgr.record_error(VALID_SID, "SomeError")

    def test_timestamp_recorded(self, mgr, created_sid):
        before = time.time()
        mgr.record_error(created_sid, "TypeError")
        after = time.time()
        session = mgr._load(created_sid)
        ts = session.error_history[0]["timestamp"]
        assert before <= ts <= after


# ── SessionManager.get_error_stats ───────────────────────────────────

class TestGetErrorStats:
    def test_no_errors(self, mgr, created_sid):
        stats = mgr.get_error_stats(created_sid)
        assert stats["error_count"] == 0
        assert stats["is_looping"] is False

    def test_missing_session(self, mgr):
        stats = mgr.get_error_stats(VALID_SID)
        assert stats["error_count"] == 0
        assert stats["is_looping"] is False

    def test_loop_detected_by_fingerprint(self, mgr, created_sid):
        mgr.record_error(created_sid, "UnicodeDecodeError", "fp_same")
        mgr.record_error(created_sid, "UnicodeDecodeError", "fp_same")
        stats = mgr.get_error_stats(created_sid, window=2)
        assert stats["is_looping"] is True
        assert stats["loop_type"] == "UnicodeDecodeError"
        assert stats["consecutive"] == 2
        assert "suggestion" in stats

    def test_loop_detected_by_error_type_prefix(self, mgr, created_sid):
        mgr.record_error(created_sid, "TypeError: expected int", "")
        mgr.record_error(created_sid, "TypeError: got str", "")
        stats = mgr.get_error_stats(created_sid, window=2)
        assert stats["is_looping"] is True
        assert stats["consecutive"] == 2

    def test_no_loop_different_fingerprints(self, mgr, created_sid):
        mgr.record_error(created_sid, "TypeError", "fp_aaa111")
        mgr.record_error(created_sid, "TypeError", "fp_bbb222")
        # different fingerprints but same type prefix — still loops on type
        stats = mgr.get_error_stats(created_sid, window=2)
        # type prefix "TypeError" matches both → is_looping True
        assert stats["is_looping"] is True

    def test_no_loop_different_types(self, mgr, created_sid):
        mgr.record_error(created_sid, "TypeError", "fp_aaa")
        mgr.record_error(created_sid, "ValueError", "fp_bbb")
        stats = mgr.get_error_stats(created_sid, window=2)
        assert stats["is_looping"] is False

    def test_error_count_correct(self, mgr, created_sid):
        for i in range(5):
            mgr.record_error(created_sid, f"Err{i}", f"fp_{i:06x}")
        stats = mgr.get_error_stats(created_sid)
        assert stats["error_count"] == 5

    def test_window_3_requires_3_same(self, mgr, created_sid):
        mgr.record_error(created_sid, "SyntaxError", "fp_x")
        mgr.record_error(created_sid, "SyntaxError", "fp_x")
        # only 2 same, window=3 → not looping
        stats = mgr.get_error_stats(created_sid, window=3)
        assert stats["is_looping"] is False

    def test_window_3_loop(self, mgr, created_sid):
        for _ in range(3):
            mgr.record_error(created_sid, "SyntaxError", "fp_x")
        stats = mgr.get_error_stats(created_sid, window=3)
        assert stats["is_looping"] is True


# ── build_session_context ─────────────────────────────────────────────

class TestBuildSessionContext:
    def _make_session(self, **kwargs):
        defaults = dict(session_id=VALID_SID, task="构建 FastAPI 后端")
        defaults.update(kwargs)
        return Session(**defaults)

    def test_contains_task(self):
        s = self._make_session()
        ctx = build_session_context(s)
        assert "构建 FastAPI 后端" in ctx
        assert "[任务目标]" in ctx

    def test_contains_anchors(self):
        s = self._make_session()
        s.anchors = ["框架: FastAPI", "数据库: SQLite"]
        ctx = build_session_context(s)
        assert "[决策锚点]" in ctx
        assert "框架: FastAPI" in ctx

    def test_no_anchors_section_when_empty(self):
        s = self._make_session()
        ctx = build_session_context(s)
        assert "[决策锚点]" not in ctx

    def test_contains_progress(self):
        s = self._make_session(progress_summary="已完成登录模块")
        ctx = build_session_context(s)
        assert "[当前进度]" in ctx
        assert "已完成登录模块" in ctx

    def test_contains_pending_issues(self):
        s = self._make_session()
        s.pending_issues = ["修复 JWT 过期", "添加单元测试"]
        ctx = build_session_context(s)
        assert "[待处理]" in ctx
        assert "修复 JWT 过期" in ctx

    def test_contains_compressed_history(self):
        s = self._make_session()
        s.compressed_history = [CompressedBlock(turn_range="1-10", summary="完成了基础架构")]
        ctx = build_session_context(s)
        assert "[历史摘要" in ctx
        assert "完成了基础架构" in ctx

    def test_contains_recent_turns(self):
        s = self._make_session()
        s.recent_turns = [TurnRecord(turn=1, action="创建项目", result="成功")]
        ctx = build_session_context(s)
        assert "[最近操作]" in ctx
        assert "turn 1" in ctx

    def test_respects_max_chars(self):
        s = self._make_session()
        s.anchors = ["anchor"] * 50
        s.project_summary = "x" * 2000
        s.recent_turns = [TurnRecord(turn=i, action="a" * 100) for i in range(20)]
        ctx = build_session_context(s, max_chars=500)
        assert len(ctx) <= 503  # allow 3 chars for "..."

    def test_empty_session_minimal_output(self):
        s = self._make_session()
        ctx = build_session_context(s)
        assert "[任务目标]" in ctx
        assert len(ctx) > 0

    def test_subtask_progress_shown(self):
        s = self._make_session()
        s.subtasks = [
            Subtask(seq=1, title="初始化项目", status="completed"),
            Subtask(seq=2, title="实现登录", status="pending"),
        ]
        s.checkpoints = [Checkpoint(subtask_seq=1, summary="项目已初始化")]
        ctx = build_session_context(s)
        assert "[步骤进度]" in ctx
        assert "[OK]" in ctx
        assert "初始化项目" in ctx

    def test_project_summary_shown(self):
        s = self._make_session(project_summary="src/\n  main.py\n  utils.py")
        ctx = build_session_context(s)
        assert "[项目结构]" in ctx
        assert "main.py" in ctx


# ── _build_loop_suggestion ────────────────────────────────────────────

class TestBuildLoopSuggestion:
    def test_known_unicode_decode(self):
        result = _build_loop_suggestion("UnicodeDecodeError", 2)
        assert "[循环警告]" in result
        assert "UnicodeDecodeError" in result
        assert "utf-8" in result  # from the known suggestion text

    def test_known_module_not_found(self):
        result = _build_loop_suggestion("ModuleNotFoundError", 3)
        assert "pip install" in result or "venv" in result

    def test_known_type_error(self):
        result = _build_loop_suggestion("TypeError", 2)
        assert "类型错误" in result

    def test_known_file_not_found(self):
        result = _build_loop_suggestion("FileNotFoundError", 2)
        assert "路径" in result or "Path" in result

    def test_known_syntax_error(self):
        result = _build_loop_suggestion("SyntaxError", 2)
        assert "语法" in result

    def test_unknown_error_type_generic(self):
        result = _build_loop_suggestion("SomeObscureError", 2)
        assert "[循环警告]" in result
        assert "kaiwu_plan" in result

    def test_consecutive_count_in_output(self):
        result = _build_loop_suggestion("TypeError", 5)
        assert "5" in result

    def test_error_type_truncated_in_output(self):
        long_type = "VeryLongErrorType" * 10
        result = _build_loop_suggestion(long_type, 2)
        # should not blow up and should contain the warning prefix
        assert "[循环警告]" in result

    def test_case_insensitive_match(self):
        # "importerror" lowercase should still match "ImportError" key
        result = _build_loop_suggestion("importerror: no module", 2)
        assert "导入错误" in result


# ── integration: full create → record_error → get_error_stats ────────

class TestIntegration:
    def test_full_error_loop_workflow(self, mgr, sessions_dir):
        sid = mgr.create("集成测试任务")
        mgr.record_error(sid, "UnicodeDecodeError", "fp_abc")
        mgr.record_error(sid, "UnicodeDecodeError", "fp_abc")
        stats = mgr.get_error_stats(sid)
        assert stats["is_looping"] is True
        assert "utf-8" in stats["suggestion"]

    def test_create_save_load_roundtrip(self, mgr, sessions_dir):
        sid = mgr.create("roundtrip task", session_id=VALID_SID)
        mgr.update_anchors(sid, ["key: value"])
        mgr.update_progress(sid, progress="halfway done", pending=["fix tests"])
        session = mgr._load(sid)
        assert session.progress_summary == "halfway done"
        assert session.pending_issues == ["fix tests"]
        assert any("key: value" in a for a in session.anchors)

    def test_context_injection_non_empty(self, mgr, sessions_dir):
        sid = mgr.create("context test")
        mgr.update_anchors(sid, ["框架: Django"])
        ctx = mgr.get_context_for_injection(sid)
        assert "[任务目标]" in ctx
        assert "context test" in ctx
