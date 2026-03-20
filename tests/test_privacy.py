"""privacy.py 脱敏函数单元测试"""

from kaiwu.privacy import (
    extract_error_category,
    sanitize_text,
    extract_summary_pattern,
    build_event_chain,
    get_platform,
)


def test_extract_error_category_python():
    assert extract_error_category("UnicodeDecodeError: 'gbk' codec...") == "UnicodeDecodeError"
    assert extract_error_category("ModuleNotFoundError: No module named 'PIL'") == "ModuleNotFoundError"
    assert extract_error_category("TypeError: expected str, got int") == "TypeError"
    assert extract_error_category("FileNotFoundError: [Errno 2] No such file") == "FileNotFoundError"
    assert extract_error_category("ConnectionRefusedError: [Errno 111]") == "ConnectionRefusedError"


def test_extract_error_category_node():
    assert extract_error_category("npm ERR! ERESOLVE unable to resolve") == "ERESOLVE"
    assert extract_error_category("ENOENT: no such file") == "ENOENT"
    assert extract_error_category("EADDRINUSE: address already in use") == "EADDRINUSE"


def test_extract_error_category_fallback():
    assert extract_error_category("some random text") == "UnknownError"
    assert extract_error_category("") == ""
    # 关键词兜底
    assert extract_error_category("codec decode failure on line 5") == "EncodingError"
    assert extract_error_category("failed to import xyz") == "ImportError"
    assert extract_error_category("permission denied for /etc/shadow") == "PermissionError"


def test_sanitize_text_paths():
    assert "<路径>" in sanitize_text("文件在 C:\\Users\\shirley\\project\\main.py")
    assert "<路径>" in sanitize_text("位于 /home/shirley/projects/api/main.py")
    assert "<路径>" in sanitize_text("读取 ./src/config.ts 失败")
    # 用户名不泄露
    assert "shirley" not in sanitize_text("文件在 C:\\Users\\shirley\\project\\main.py")
    assert "shirley" not in sanitize_text("位于 /home/shirley/projects/api/main.py")


def test_sanitize_text_urls_and_ips():
    assert "<URL>" in sanitize_text("访问 https://api.company.com/v1/users")
    assert "<IP>" in sanitize_text("连接到 192.168.1.100")
    assert "<邮件>" in sanitize_text("联系 admin@company.com")
    assert ":<端口>" in sanitize_text("监听在 :3000 端口")
    # 原值不泄露
    assert "company.com" not in sanitize_text("访问 https://api.company.com/v1/users")
    assert "192.168.1.100" not in sanitize_text("连接到 192.168.1.100")


def test_sanitize_text_clean():
    """不含敏感信息的文本不应被改变"""
    clean = "用 FastAPI 实现了用户认证"
    assert sanitize_text(clean) == clean


def test_extract_summary_pattern():
    raw = "用 FastAPI 在 /api/v1/users 创建了 UserProfile 接口，使用 SQLAlchemy"
    result = extract_summary_pattern(raw)
    assert "/api/v1/users" not in result  # 路径被去掉
    assert "UserProfile" not in result    # CamelCase 被去掉
    assert len(result) <= 150


def test_extract_summary_pattern_empty():
    assert extract_summary_pattern("") == ""
    assert extract_summary_pattern(None) == ""


def test_build_event_chain():
    events = [
        {"event_type": "error"},
        {"event_type": "fix"},
        {"event_type": "error"},
        {"event_type": "fix"},
        {"event_type": "success"},
    ]
    assert build_event_chain(events) == "error->fix->error->fix->success"
    assert build_event_chain([]) == ""
    assert build_event_chain([{"event_type": "success"}]) == "success"


def test_get_platform():
    p = get_platform()
    assert p in ("windows", "mac", "linux", "other")


if __name__ == "__main__":
    import sys
    # 简易运行器
    passed = 0
    failed = 0
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
