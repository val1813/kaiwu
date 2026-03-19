"""任务分类器单元测试"""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pytest

from kaiwu.task_classifier import (
    classify_task,
    extract_task_tokens,
    should_inject_knowledge,
    TaskVerdict,
)


# ── classify_task ─────────────────────────────────────────────────

def test_classify_task_pure_algorithm_normal():
    verdict = classify_task("实现一个快速排序算法", turns=0, error_count=0)
    assert verdict.level == "normal"


def test_classify_task_deploy_active():
    verdict = classify_task("用 nginx 部署 FastAPI 服务到服务器", turns=0, error_count=0)
    assert verdict.level == "active"


def test_classify_task_high_turns_high_errors_rescue():
    verdict = classify_task("修复登录 bug", turns=5, error_count=3)
    assert verdict.level == "rescue"


def test_classify_task_high_turns_rescue():
    verdict = classify_task("实现功能", turns=10, error_count=0)
    assert verdict.level == "rescue"


def test_classify_task_looping_rescue():
    verdict = classify_task("修复 bug", turns=3, error_count=1, is_looping=True)
    assert verdict.level == "rescue"


def test_classify_task_normal_coding():
    verdict = classify_task("写一个 Python 函数计算斐波那契数列", turns=0, error_count=0)
    assert verdict.level == "normal"


def test_classify_task_empty_task():
    verdict = classify_task("", turns=0, error_count=0)
    assert verdict.level == "normal"
    assert verdict.inject_knowledge is False
    assert verdict.call_llm is False


def test_classify_task_returns_taskverdict():
    verdict = classify_task("实现登录功能")
    assert isinstance(verdict, TaskVerdict)
    assert verdict.level in ("normal", "active", "rescue")
    assert isinstance(verdict.inject_knowledge, bool)
    assert isinstance(verdict.inject_experience, bool)
    assert isinstance(verdict.call_llm, bool)


def test_classify_task_rescue_injects_all():
    verdict = classify_task("修复 bug", turns=0, error_count=0, is_looping=True)
    assert verdict.inject_knowledge is True
    assert verdict.inject_experience is True
    assert verdict.call_llm is True


def test_classify_task_active_injects_all():
    verdict = classify_task("用 docker 部署应用到服务器", turns=0, error_count=0)
    assert verdict.level == "active"
    assert verdict.inject_knowledge is True
    assert verdict.inject_experience is True
    assert verdict.call_llm is True


def test_classify_task_normal_experience_always_injected():
    verdict = classify_task("写一个排序函数", turns=0, error_count=0)
    assert verdict.inject_experience is True
    assert verdict.call_llm is False


def test_classify_task_china_keywords_active():
    # "微信" + "wechat" = 2 hits in china category → active
    verdict = classify_task("处理微信 wechat 支付回调接口", turns=0, error_count=0)
    assert verdict.level == "active"


def test_classify_task_encoding_active():
    verdict = classify_task("解决 GBK 编码乱码问题", turns=0, error_count=0)
    assert verdict.level == "active"


# ── extract_task_tokens ───────────────────────────────────────────

def test_extract_task_tokens_english():
    tokens = extract_task_tokens("implement authentication module")
    assert "implement" in tokens
    assert "authentication" in tokens
    assert "module" in tokens


def test_extract_task_tokens_chinese_2gram():
    tokens = extract_task_tokens("实现用户登录")
    assert "用户" in tokens or "登录" in tokens


def test_extract_task_tokens_returns_set():
    tokens = extract_task_tokens("test task")
    assert isinstance(tokens, set)


def test_extract_task_tokens_min_length_3_english():
    tokens = extract_task_tokens("do it now")
    # "do", "it" are < 3 chars, "now" is 3 chars
    assert "do" not in tokens
    assert "it" not in tokens
    assert "now" in tokens


def test_extract_task_tokens_mixed():
    tokens = extract_task_tokens("implement 用户登录 module")
    assert "implement" in tokens
    assert "module" in tokens
    # Chinese 2-gram
    assert "用户" in tokens or "登录" in tokens


def test_extract_task_tokens_empty():
    tokens = extract_task_tokens("")
    assert tokens == set()


def test_extract_task_tokens_no_stopwords_removal():
    # extract_task_tokens does NOT filter stopwords (unlike _extract_keywords)
    # it just extracts 3+ char english words and chinese 2-grams
    tokens = extract_task_tokens("the function")
    assert "the" in tokens  # 3 chars, included
    assert "function" in tokens


# ── should_inject_knowledge ───────────────────────────────────────

def test_should_inject_china_kb_gbk():
    assert should_inject_knowledge("解决 GBK 编码问题", "china_kb") is True


def test_should_inject_china_kb_wechat():
    assert should_inject_knowledge("实现微信登录功能", "china_kb") is True


def test_should_inject_china_kb_stock():
    assert should_inject_knowledge("用 akshare 获取 A股数据", "china_kb") is True


def test_should_inject_china_kb_no_match():
    assert should_inject_knowledge("implement user authentication", "china_kb") is False


def test_should_inject_python_compat():
    assert should_inject_knowledge("升级 Python 版本兼容性问题", "python_compat") is True


def test_should_inject_python_compat_no_match():
    assert should_inject_knowledge("写一个排序算法", "python_compat") is False


def test_should_inject_deps_pitfalls_pip():
    assert should_inject_knowledge("pip install numpy 失败", "deps_pitfalls") is True


def test_should_inject_deps_pitfalls_npm():
    assert should_inject_knowledge("npm install 依赖冲突", "deps_pitfalls") is True


def test_should_inject_deps_pitfalls_no_match():
    assert should_inject_knowledge("实现快速排序", "deps_pitfalls") is False


def test_should_inject_tool_priming_mcp():
    assert should_inject_knowledge("配置 MCP 工具调用", "tool_priming") is True


def test_should_inject_tool_priming_no_match():
    assert should_inject_knowledge("写一个函数", "tool_priming") is False


def test_should_inject_unknown_kb():
    assert should_inject_knowledge("任何任务", "nonexistent_kb") is False


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
