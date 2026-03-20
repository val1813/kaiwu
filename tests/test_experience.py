"""经验库核心逻辑单元测试"""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
import tempfile
import shutil
import time
from pathlib import Path

import pytest

from kaiwu.storage.experience import (
    ExperienceStore,
    Experience,
    ToolStep,
    TraceStep,
    MEMORY_TAG_IMPL,
    MEMORY_TAG_ERR,
    MEMORY_TAG_METHOD,
    MEMORY_TAG_PREF,
    MEMORY_TAG_PROC,
    infer_memory_tag,
    _extract_keywords,
    _keyword_overlap,
    _sanitize_assertion,
    _make_exp_id,
    _TfIdfIndex,
)


# ── TraceStep ──────────────────────────────────────────────────────

def test_tracestep_to_dict_basic():
    s = TraceStep(turn=1, action="读取 config.py", outcome="发现 bug", success=True)
    d = s.to_dict()
    assert d["turn"] == 1
    assert d["action"] == "读取 config.py"
    assert d["outcome"] == "发现 bug"
    assert d["success"] is True
    assert d["pivot"] is False


def test_tracestep_to_dict_truncates_at_120():
    long_action = "A" * 200
    long_outcome = "B" * 200
    s = TraceStep(turn=2, action=long_action, outcome=long_outcome, success=False)
    d = s.to_dict()
    assert len(d["action"]) == 120
    assert len(d["outcome"]) == 120


def test_tracestep_from_dict_basic():
    d = {"turn": 3, "action": "修改 auth", "outcome": "测试通过", "success": True, "pivot": True}
    s = TraceStep.from_dict(d)
    assert s.turn == 3
    assert s.action == "修改 auth"
    assert s.pivot is True


def test_tracestep_from_dict_truncates():
    d = {"turn": 1, "action": "X" * 200, "outcome": "Y" * 200, "success": True}
    s = TraceStep.from_dict(d)
    assert len(s.action) == 120
    assert len(s.outcome) == 120


def test_tracestep_from_dict_defaults():
    s = TraceStep.from_dict({})
    assert s.turn == 0
    assert s.action == ""
    assert s.success is True
    assert s.pivot is False


# ── ToolStep ──────────────────────────────────────────────────────

def test_toolstep_to_dict():
    ts = ToolStep(tool_name="read_file", params_summary="config.py", result_summary="ok", success=True)
    d = ts.to_dict()
    assert d["tool_name"] == "read_file"
    assert d["success"] is True


def test_toolstep_from_dict():
    d = {"tool_name": "write_file", "params_summary": "out.py", "result_summary": "written", "success": False}
    ts = ToolStep.from_dict(d)
    assert ts.tool_name == "write_file"
    assert ts.success is False


def test_toolstep_roundtrip():
    ts = ToolStep(tool_name="bash", params_summary="ls -la", result_summary="files listed", success=True)
    ts2 = ToolStep.from_dict(ts.to_dict())
    assert ts2.tool_name == ts.tool_name
    assert ts2.params_summary == ts.params_summary


# ── Experience ────────────────────────────────────────────────────

def test_experience_to_dict_basic():
    exp = Experience(
        exp_id="abc123",
        task_type="web",
        task_description="实现用户登录功能",
        fix_strategy="用 JWT 做认证",
        summary="JWT 认证实现",
        memory_tag=MEMORY_TAG_IMPL,
    )
    d = exp.to_dict()
    assert d["exp_id"] == "abc123"
    assert d["task_type"] == "web"
    assert d["memory_tag"] == MEMORY_TAG_IMPL
    assert "deprecated" not in d  # 未 deprecated 时不写入


def test_experience_to_dict_deprecated():
    exp = Experience(exp_id="x", task_type="debug", task_description="fix bug")
    exp.deprecated = True
    exp.deprecated_at = 1234567890.0
    d = exp.to_dict()
    assert d["deprecated"] is True
    assert d["deprecated_at"] == 1234567890.0


def test_experience_from_dict_basic():
    d = {
        "exp_id": "exp001",
        "task_type": "react",
        "task_description": "实现组件",
        "summary": "用 hooks 实现",
        "fix_strategy": "用 hooks",
        "memory_tag": MEMORY_TAG_PREF,
        "project_name": "myapp",
    }
    exp = Experience.from_dict(d)
    assert exp.exp_id == "exp001"
    assert exp.memory_tag == MEMORY_TAG_PREF
    assert exp.project_name == "myapp"


def test_experience_from_dict_tool_sequence():
    d = {
        "exp_id": "e2",
        "task_type": "debug",
        "task_description": "fix import error",
        "tool_sequence": [
            {"tool_name": "bash", "params_summary": "pip install", "result_summary": "ok", "success": True}
        ],
    }
    exp = Experience.from_dict(d)
    assert len(exp.tool_sequence) == 1
    assert exp.tool_sequence[0].tool_name == "bash"


def test_experience_effective_summary_priority():
    exp = Experience(exp_id="e", task_type="web", task_description="task")
    assert exp.effective_summary == ""

    exp.problem_pattern = "pattern"
    assert exp.effective_summary == "pattern"

    exp.fix_strategy = "strategy"
    assert exp.effective_summary == "strategy"

    exp.summary = "summary"
    assert exp.effective_summary == "summary"


def test_experience_to_few_shot_contains_task():
    exp = Experience(
        exp_id="e",
        task_type="web",
        task_description="实现登录",
        problem_pattern="JWT 问题",
        fix_strategy="用 RS256",
        key_steps=["步骤1", "步骤2"],
        turns_taken=3,
    )
    text = exp.to_few_shot()
    assert "[任务]" in text
    assert "实现登录" in text
    assert "[修改策略]" in text
    assert "[关键步骤]" in text
    assert "3 轮完成" in text


def test_experience_to_few_shot_tool_sequence_fallback():
    ts = ToolStep(tool_name="read", params_summary="file.py", result_summary="content", success=True)
    exp = Experience(
        exp_id="e",
        task_type="debug",
        task_description="debug task",
        tool_sequence=[ts],
        turns_taken=2,
    )
    text = exp.to_few_shot()
    assert "[关键步骤]" in text
    assert "read" in text


# ── infer_memory_tag ──────────────────────────────────────────────

def test_infer_memory_tag_failure_returns_err():
    assert infer_memory_tag("web", "任何摘要", False) == MEMORY_TAG_ERR


def test_infer_memory_tag_method_keywords():
    assert infer_memory_tag("web", "这是一个方法论模式", True) == MEMORY_TAG_METHOD
    assert infer_memory_tag("web", "best approach for deployment", True) == MEMORY_TAG_METHOD
    assert infer_memory_tag("web", "design pattern for auth", True) == MEMORY_TAG_METHOD


def test_infer_memory_tag_error_keywords():
    assert infer_memory_tag("web", "遇到报错需要修复", True) == MEMORY_TAG_ERR
    assert infer_memory_tag("web", "fix the bug in auth", True) == MEMORY_TAG_ERR
    assert infer_memory_tag("web", "traceback in line 42", True) == MEMORY_TAG_ERR


def test_infer_memory_tag_pref_keywords():
    assert infer_memory_tag("web", "用户偏好使用 TypeScript", True) == MEMORY_TAG_PREF
    assert infer_memory_tag("web", "always use async/await", True) == MEMORY_TAG_PREF
    assert infer_memory_tag("web", "命名规范要用驼峰", True) == MEMORY_TAG_PREF


def test_infer_memory_tag_task_type_debug():
    assert infer_memory_tag("debug", "完成了调试", True) == MEMORY_TAG_ERR


def test_infer_memory_tag_task_type_code_review():
    assert infer_memory_tag("code_review", "代码审查完成", True) == MEMORY_TAG_PREF


def test_infer_memory_tag_default_impl():
    assert infer_memory_tag("web", "实现了用户注册功能", True) == MEMORY_TAG_IMPL
    assert infer_memory_tag("unknown_type", "完成了某个功能", True) == MEMORY_TAG_IMPL


# ── _extract_keywords ─────────────────────────────────────────────

def test_extract_keywords_english_unigram():
    tokens = _extract_keywords("implement authentication module")
    assert "implement" in tokens or "authentication" in tokens or "module" in tokens


def test_extract_keywords_chinese_2gram():
    tokens = _extract_keywords("实现用户登录功能")
    # 2-gram 滑动窗口
    assert "用户" in tokens or "登录" in tokens or "功能" in tokens


def test_extract_keywords_stopwords_filtered():
    tokens = _extract_keywords("the file is in the class")
    # "the", "is", "in", "file", "class" 都是停用词
    assert "the" not in tokens
    assert "is" not in tokens


def test_extract_keywords_bigram():
    tokens = _extract_keywords("implement authentication")
    # bigram: implement_authentication
    assert "implement_authentication" in tokens


def test_extract_keywords_max_30():
    long_text = " ".join([f"word{i}" for i in range(50)])
    tokens = _extract_keywords(long_text)
    assert len(tokens) <= 30


# ── _keyword_overlap ──────────────────────────────────────────────

def test_keyword_overlap_identical():
    text = "implement user authentication module"
    score = _keyword_overlap(text, text)
    assert score == 1.0


def test_keyword_overlap_no_overlap():
    score = _keyword_overlap("implement authentication", "数据库查询优化")
    assert score == 0.0


def test_keyword_overlap_partial():
    score = _keyword_overlap("implement authentication module", "implement database module")
    assert 0.0 < score < 1.0


def test_keyword_overlap_empty():
    assert _keyword_overlap("", "something") == 0.0
    assert _keyword_overlap("something", "") == 0.0


# ── _sanitize_assertion ───────────────────────────────────────────

def test_sanitize_assertion_year():
    result = _sanitize_assertion("这是2024年最新推荐的方案")
    assert "2024" not in result


def test_sanitize_assertion_performance():
    result = _sanitize_assertion("使用这个方案快10倍以上")
    assert "10倍" not in result
    assert "显著提升效率" in result


def test_sanitize_assertion_subjective_rank():
    result = _sanitize_assertion("这是最好的解决方案")
    assert "最好的" not in result
    assert "常用的" in result


def test_sanitize_assertion_no_change():
    text = "用 FastAPI 实现了用户认证接口"
    assert _sanitize_assertion(text) == text


def test_sanitize_assertion_must_use():
    result = _sanitize_assertion("必须用 uvicorn 启动服务")
    assert "必须用" not in result
    assert "建议用" in result


# ── ExperienceStore (tempfile 隔离) ───────────────────────────────

@pytest.fixture
def store(tmp_path):
    """每个测试用独立临时目录"""
    exp_path = tmp_path / "experiences.json"
    s = ExperienceStore(path=exp_path)
    # 清空预置经验（避免干扰）
    s._data.clear()
    return s


def test_store_record_normal(store):
    exp = store.record(
        task="实现用户登录功能，使用 JWT 认证",
        task_type="web",
        success=True,
        summary="用 JWT 实现登录",
    )
    assert exp is not None
    assert exp.task_type == "web"
    assert exp.success is True


def test_store_record_short_task_skipped(store):
    exp = store.record(task="fix bug", task_type="debug", success=True)
    assert exp is None


def test_store_record_duplicate_increments_hit_count(store):
    task = "实现用户登录功能，使用 JWT 认证"
    exp1 = store.record(task=task, task_type="web", success=True, summary="JWT 登录")
    assert exp1 is not None
    initial_hit = exp1.hit_count

    exp2 = store.record(task=task, task_type="web", success=True, summary="JWT 登录")
    assert exp2 is not None
    assert exp2.hit_count == initial_hit + 1


def test_store_record_explicit_memory_tag_preserved(store):
    exp = store.record(
        task="实现用户登录功能，使用 JWT 认证",
        task_type="web",
        success=True,
        summary="JWT 登录实现",
        memory_tag=MEMORY_TAG_METHOD,
    )
    assert exp is not None
    assert exp.memory_tag == MEMORY_TAG_METHOD


def test_store_retrieve_returns_relevant(store):
    store.record(
        task="实现用户登录功能，使用 JWT 认证",
        task_type="web",
        success=True,
        summary="JWT 登录",
    )
    results = store.retrieve("用户登录 JWT", task_type="web")
    assert len(results) >= 1


def test_store_retrieve_deprecated_filtered(store):
    exp = store.record(
        task="实现用户登录功能，使用 JWT 认证",
        task_type="web",
        success=True,
        summary="JWT 登录",
    )
    assert exp is not None
    store._soft_delete(exp.exp_id)
    results = store.retrieve("用户登录 JWT", task_type="web")
    assert all(r.exp_id != exp.exp_id for r in results)


def test_store_retrieve_project_name_filter(store):
    store.record(
        task="实现用户登录功能，使用 JWT 认证",
        task_type="web",
        success=True,
        summary="JWT 登录",
        project_name="project_a",
    )
    # 查询 project_b 不应看到 project_a 的经验
    results = store.retrieve("用户登录 JWT", task_type="web", project_name="project_b")
    assert all(r.project_name != "project_a" for r in results)


def test_store_inject_into_context_fail_exp_first(store):
    # 写入一条失败经验
    store.record(
        task="实现用户登录功能，使用 JWT 认证",
        task_type="web",
        success=False,
        error_summary="JWT secret 未配置导致 500",
    )
    # 写入一条成功经验
    store.record(
        task="实现用户登录功能，使用 JWT 认证成功版",
        task_type="web",
        success=True,
        summary="JWT 登录成功实现",
    )
    ctx = store.inject_into_context("用户登录 JWT", task_type="web")
    if ctx:
        # 失败经验应在成功经验之前（WARNING 标记）
        warn_pos = ctx.find("WARNING")
        impl_pos = ctx.find("[implementation_detail]")
        if warn_pos != -1 and impl_pos != -1:
            assert warn_pos < impl_pos


def test_store_inject_into_context_methodology_label(store):
    store._data["method_exp"] = Experience(
        exp_id="method_exp",
        task_type="web",
        task_description="用户登录 JWT 方法论",
        summary="先验证 token 再查数据库",
        memory_tag=MEMORY_TAG_METHOD,
        success=True,
        problem_keywords=["用户", "登录", "jwt", "认证"],
    )
    ctx = store.inject_into_context("用户登录 JWT 认证", task_type="web")
    if ctx:
        assert "[方法论]" in ctx


def test_store_inject_into_context_normal_success(store):
    store._data["impl_exp"] = Experience(
        exp_id="impl_exp",
        task_type="web",
        task_description="用户登录 JWT 实现",
        summary="用 PyJWT 库实现 token 签发",
        memory_tag=MEMORY_TAG_IMPL,
        success=True,
        problem_keywords=["用户", "登录", "jwt", "认证"],
    )
    ctx = store.inject_into_context("用户登录 JWT 认证", task_type="web")
    if ctx:
        assert "[历史经验参考" in ctx


def test_store_soft_delete(store):
    exp = store.record(
        task="实现用户登录功能，使用 JWT 认证",
        task_type="web",
        success=True,
        summary="JWT 登录",
    )
    assert exp is not None
    result = store._soft_delete(exp.exp_id)
    assert result is True
    assert store._data[exp.exp_id].deprecated is True


def test_store_soft_delete_nonexistent(store):
    assert store._soft_delete("nonexistent_id") is False


def test_store_update_distill(store):
    exp = store.record(
        task="实现用户登录功能，使用 JWT 认证",
        task_type="web",
        success=True,
        summary="初始摘要",
    )
    assert exp is not None
    result = store.update_distill(exp.exp_id, "蒸馏后的摘要", ["步骤1", "步骤2"])
    assert result is True
    assert store._data[exp.exp_id].summary == "蒸馏后的摘要"


def test_store_trim_removes_excess(store):
    from kaiwu.storage.experience import MAX_EXPERIENCES
    # 写入超过上限的经验
    for i in range(MAX_EXPERIENCES + 5):
        task = f"实现功能模块 {i} 号，包含完整的业务逻辑处理"
        exp_id = _make_exp_id(task, "web")
        store._data[exp_id] = Experience(
            exp_id=exp_id,
            task_type="web",
            task_description=task,
            summary=f"摘要 {i}",
            timestamp=time.time() + i,
        )
    store._trim()
    assert len(store._data) <= MAX_EXPERIENCES


# ── _TfIdfIndex ───────────────────────────────────────────────────

def test_tfidf_query_returns_relevant():
    idx = _TfIdfIndex()
    idx.add("doc1", "implement user authentication JWT token")
    idx.add("doc2", "database query optimization index")
    idx.add("doc3", "user login JWT authentication flow")
    results = idx.query("JWT authentication", top_k=2)
    doc_ids = [r[0] for r in results]
    assert "doc1" in doc_ids or "doc3" in doc_ids


def test_tfidf_query_scores_between_0_and_1():
    idx = _TfIdfIndex()
    idx.add("doc1", "implement authentication module")
    idx.add("doc2", "database optimization query")
    results = idx.query("authentication", top_k=5)
    for _, score in results:
        assert 0.0 < score <= 1.0


def test_tfidf_remove_excludes_doc():
    idx = _TfIdfIndex()
    idx.add("doc1", "implement user authentication JWT")
    idx.add("doc2", "database query optimization")
    idx.remove("doc1")
    results = idx.query("JWT authentication", top_k=5)
    doc_ids = [r[0] for r in results]
    assert "doc1" not in doc_ids


def test_tfidf_empty_query_returns_empty():
    idx = _TfIdfIndex()
    idx.add("doc1", "implement authentication")
    results = idx.query("", top_k=5)
    assert results == []


def test_tfidf_empty_index_returns_empty():
    idx = _TfIdfIndex()
    results = idx.query("authentication JWT", top_k=5)
    assert results == []


def test_tfidf_reranking_in_retrieve(store):
    """TF-IDF 精排：多候选时应返回语义更相关的经验"""
    # 写入多条经验，确保候选数 > top_k 触发精排
    for i in range(5):
        task = f"实现用户登录功能，使用 JWT 认证，模块 {i}"
        exp_id = _make_exp_id(task, "web")
        store._data[exp_id] = Experience(
            exp_id=exp_id,
            task_type="web",
            task_description=task,
            summary=f"JWT 登录实现方案 {i}",
            memory_tag=MEMORY_TAG_IMPL,
            success=True,
            problem_keywords=_extract_keywords(task),
        )
        store._tfidf.add(exp_id, f"{task} JWT 登录实现方案 {i}")

    results = store.retrieve("用户登录 JWT 认证", task_type="web", top_k=2)
    assert len(results) <= 2


def test_tfidf_index_built_on_init(tmp_path):
    """__init__ 时应自动构建 TF-IDF 索引"""
    exp_path = tmp_path / "experiences.json"
    s = ExperienceStore(path=exp_path)
    s._data.clear()
    task = "实现用户登录功能，使用 JWT 认证"
    exp_id = _make_exp_id(task, "web")
    s._data[exp_id] = Experience(
        exp_id=exp_id,
        task_type="web",
        task_description=task,
        summary="JWT 登录",
        success=True,
        problem_keywords=_extract_keywords(task),
    )
    s._save()

    # 重新加载，验证索引被构建
    s2 = ExperienceStore(path=exp_path)
    assert exp_id in s2._tfidf._docs


def test_tfidf_soft_delete_removes_from_index(store):
    """软删除后 TF-IDF 索引中不应再有该文档"""
    exp = store.record(
        task="实现用户登录功能，使用 JWT 认证",
        task_type="web",
        success=True,
        summary="JWT 登录",
    )
    assert exp is not None
    assert exp.exp_id in store._tfidf._docs
    store._soft_delete(exp.exp_id)
    assert exp.exp_id not in store._tfidf._docs


if __name__ == "__main__":
    passed = failed = 0
    for name, func in list(globals().items()):
        if name.startswith("test_") and callable(func):
            try:
                func()
                print(f"  PASS: {name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL: {name} — {e}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
