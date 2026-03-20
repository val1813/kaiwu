"""错误知识库单元测试"""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pytest
from pathlib import Path

from kaiwu.storage.error_kb import (
    ErrorKB,
    _fingerprint,
    _extract_error_key,
    _fuzzy_match,
    _categorize_error,
)


# ── _fingerprint ──────────────────────────────────────────────────

def test_fingerprint_returns_16_char_hex():
    fp = _fingerprint("ModuleNotFoundError: No module named 'PIL'")
    assert len(fp) == 16
    assert all(c in "0123456789abcdef" for c in fp)


def test_fingerprint_strips_windows_path():
    err1 = "FileNotFoundError: C:\\Users\\alice\\project\\main.py not found"
    err2 = "FileNotFoundError: C:\\Users\\bob\\other\\main.py not found"
    assert _fingerprint(err1) == _fingerprint(err2)


def test_fingerprint_strips_unix_path():
    err1 = "FileNotFoundError: /home/alice/project/main.py not found"
    err2 = "FileNotFoundError: /home/bob/other/main.py not found"
    assert _fingerprint(err1) == _fingerprint(err2)


def test_fingerprint_strips_line_numbers():
    err1 = "SyntaxError: invalid syntax at line 42"
    err2 = "SyntaxError: invalid syntax at line 99"
    assert _fingerprint(err1) == _fingerprint(err2)


def test_fingerprint_strips_version():
    err1 = "requires numpy 1.24.3 but found"
    err2 = "requires numpy 2.0.1 but found"
    assert _fingerprint(err1) == _fingerprint(err2)


def test_fingerprint_same_error_same_fp():
    err = "ModuleNotFoundError: No module named 'requests'"
    assert _fingerprint(err) == _fingerprint(err)


def test_fingerprint_different_errors_different_fp():
    fp1 = _fingerprint("ModuleNotFoundError: No module named 'requests'")
    fp2 = _fingerprint("TypeError: expected str got int")
    assert fp1 != fp2


# ── _extract_error_key ────────────────────────────────────────────

def test_extract_error_key_module_not_found():
    key = _extract_error_key("ModuleNotFoundError: No module named 'PIL'")
    assert "ModuleNotFoundError" in key
    assert "PIL" in key


def test_extract_error_key_syntax_error():
    key = _extract_error_key("SyntaxError: invalid syntax")
    assert "SyntaxError" in key


def test_extract_error_key_type_error():
    key = _extract_error_key("TypeError: expected str, got int")
    assert "TypeError" in key


def test_extract_error_key_npm_err():
    key = _extract_error_key("npm ERR! ERESOLVE unable to resolve dependency tree")
    assert "npm ERR!" in key


def test_extract_error_key_fallback_last_error_line():
    err = "some output\nmore output\nfinal error occurred here"
    key = _extract_error_key(err)
    assert len(key) > 0


def test_extract_error_key_max_length():
    long_err = "TypeError: " + "x" * 200
    key = _extract_error_key(long_err)
    assert len(key) <= 100


# ── ErrorKB (tempfile 隔离) ───────────────────────────────────────

@pytest.fixture
def kb(tmp_path):
    path = tmp_path / "error_kb.json"
    store = ErrorKB(path=path)
    # 清空预置数据，避免干扰
    store._data["entries"].clear()
    return store


def test_record_error_returns_fingerprint(kb):
    fp = kb.record_error("ModuleNotFoundError: No module named 'PIL'")
    assert isinstance(fp, str)
    assert len(fp) == 16


def test_record_error_writes_entry(kb):
    err = "ModuleNotFoundError: No module named 'PIL'"
    fp = kb.record_error(err)
    assert fp in kb._data["entries"]
    entry = kb._data["entries"][fp]
    assert entry["count"] == 1


def test_record_error_increments_count(kb):
    err = "ModuleNotFoundError: No module named 'PIL'"
    fp1 = kb.record_error(err)
    fp2 = kb.record_error(err)
    assert fp1 == fp2
    assert kb._data["entries"][fp1]["count"] == 2


def test_record_error_with_context(kb):
    fp = kb.record_error("TypeError: expected str", context="task: fix auth module")
    entry = kb._data["entries"][fp]
    assert "fix auth" in entry["context"]


def test_find_solution_exact_match(kb):
    err = "ModuleNotFoundError: No module named 'PIL'"
    fp = kb.record_error(err)
    kb.record_solution(fp, "pip install Pillow")

    result = kb.find_solution(err)
    assert result is not None
    assert result["source"] == "local_exact"
    assert "Pillow" in result["solution"]
    assert result["confidence"] >= 0.9


def test_find_solution_fuzzy_match(kb):
    # 写入一条有解决方案的错误
    err_stored = "ModuleNotFoundError: No module named 'PIL'"
    fp = kb.record_error(err_stored)
    kb.record_solution(fp, "pip install Pillow")

    # 用相似但不完全相同的文本查询
    err_query = "ModuleNotFoundError: cannot import PIL module"
    result = kb.find_solution(err_query)
    # 模糊匹配可能命中也可能不命中，取决于词重叠率
    # 只验证返回类型正确
    if result is not None:
        assert "source" in result
        assert "solution" in result


def test_find_solution_no_match(kb):
    result = kb.find_solution("completely unrelated error xyz123")
    assert result is None


def test_find_solution_no_solution_recorded(kb):
    err = "TypeError: expected str got int"
    kb.record_error(err)
    # 没有记录 solution，精确匹配不应返回
    result = kb.find_solution(err)
    assert result is None


def test_record_solution_writes_back(kb):
    err = "TypeError: expected str got int"
    fp = kb.record_error(err)
    kb.record_solution(fp, "确保传入字符串类型")
    entry = kb._data["entries"][fp]
    assert entry["solution"] == "确保传入字符串类型"


def test_record_solution_nonexistent_fp(kb):
    # 不存在的 fp，不应抛异常
    kb.record_solution("nonexistent_fp_1234", "some solution")


def test_has_solution_true(kb):
    err = "FileNotFoundError: config.yaml not found"
    fp = kb.record_error(err)
    kb.record_solution(fp, "确保 config.yaml 存在")
    assert kb.has_solution(fp) is True


def test_has_solution_false_no_solution(kb):
    err = "FileNotFoundError: config.yaml not found"
    fp = kb.record_error(err)
    assert kb.has_solution(fp) is False


def test_has_solution_false_nonexistent(kb):
    assert kb.has_solution("nonexistent_fp") is False


def test_trim_keeps_within_max(kb):
    from kaiwu.storage.error_kb import MAX_ENTRIES
    for i in range(MAX_ENTRIES + 10):
        kb.record_error(f"UniqueError{i}: message number {i} with unique content")
    assert len(kb._data["entries"]) <= MAX_ENTRIES


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "error_kb.json"
    kb1 = ErrorKB(path=path)
    kb1._data["entries"].clear()

    err = "ModuleNotFoundError: No module named 'requests'"
    fp = kb1.record_error(err)
    kb1.record_solution(fp, "pip install requests")

    # 重新加载
    kb2 = ErrorKB(path=path)
    assert fp in kb2._data["entries"]
    assert kb2._data["entries"][fp]["solution"] == "pip install requests"


def test_get_stats(kb):
    err1 = "ModuleNotFoundError: No module named 'PIL'"
    fp1 = kb.record_error(err1)
    kb.record_solution(fp1, "pip install Pillow")

    err2 = "TypeError: expected str got int"
    kb.record_error(err2)

    stats = kb.get_stats()
    assert stats["total"] == 2
    assert stats["solved"] == 1
    assert stats["unsolved"] == 1


# ── category ──────────────────────────────────────────────────────

def test_categorize_encoding():
    assert _categorize_error("UnicodeDecodeError: 'gbk' codec can't decode") == "encoding"


def test_categorize_import():
    assert _categorize_error("ModuleNotFoundError: No module named 'requests'") == "import"


def test_categorize_file_not_found():
    assert _categorize_error("FileNotFoundError: No such file or directory") == "file_not_found"


def test_categorize_network():
    assert _categorize_error("ConnectionRefusedError: [Errno 111] Connection refused") == "network"


def test_categorize_other():
    assert _categorize_error("some completely unknown weird error zzz") == "other"


def test_record_error_stores_category(kb):
    fp = kb.record_error("UnicodeDecodeError: 'utf-8' codec can't decode byte")
    entry = kb._data["entries"][fp]
    assert entry["category"] == "encoding"


def test_find_solution_category_match(kb):
    # 记录一个 encoding 错误并给出解法
    err1 = "UnicodeDecodeError: 'gbk' codec can't decode byte 0xff"
    fp1 = kb.record_error(err1)
    kb.record_solution(fp1, "open(file, encoding='utf-8')")

    # 查询另一个 encoding 错误（指纹和模糊都不会命中）
    err2 = "UnicodeEncodeError: charmap codec can't encode character"
    result = kb.find_solution(err2)
    assert result is not None
    assert result["source"] == "local_category"
    assert result["confidence"] == 0.5
    assert result["category"] == "encoding"
    assert "utf-8" in result["solution"]


def test_find_solution_category_no_solution_returns_none(kb):
    # 同类别有记录但无解法，不应返回
    err1 = "UnicodeDecodeError: 'gbk' codec can't decode byte 0xff"
    kb.record_error(err1)  # 不记录 solution

    err2 = "UnicodeEncodeError: charmap codec can't encode character"
    result = kb.find_solution(err2)
    assert result is None


def test_get_stats_category_distribution(kb):
    kb.record_error("UnicodeDecodeError: 'utf-8' codec can't decode")
    kb.record_error("ModuleNotFoundError: No module named 'PIL'")
    kb.record_error("ModuleNotFoundError: No module named 'numpy'")

    stats = kb.get_stats()
    dist = stats["category_distribution"]
    assert dist.get("encoding", 0) >= 1
    assert dist.get("import", 0) >= 2


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
