"""Tests for kaiwu.server — _clamp function and input validation constants."""

import pytest

from kaiwu.server import (
    _clamp,
    MAX_TASK_LEN,
    MAX_ERROR_TEXT_LEN,
    MAX_CONTEXT_LEN,
    MAX_HISTORY_LEN,
    MAX_TRACE_LEN,
)


# ── _clamp ─────────────────────────────────────────────────────────────────

class TestClamp:
    def test_short_text_unchanged(self):
        text = "hello world"
        assert _clamp(text, 100) == text

    def test_text_at_exact_limit_unchanged(self):
        text = "x" * 50
        assert _clamp(text, 50) == text

    def test_text_over_limit_truncated(self):
        text = "a" * 200
        result = _clamp(text, 100)
        assert result != text
        assert result.startswith("a" * 100)

    def test_truncated_result_contains_original_length(self):
        text = "a" * 200
        result = _clamp(text, 100)
        assert "200" in result

    def test_truncated_result_contains_ellipsis_marker(self):
        text = "b" * 500
        result = _clamp(text, 50)
        assert "..." in result or "截断" in result

    def test_truncation_prefix_is_exactly_max_len_chars(self):
        text = "z" * 300
        max_len = 150
        result = _clamp(text, max_len)
        # The first max_len characters must be the original text prefix
        assert result[:max_len] == text[:max_len]

    def test_empty_string_unchanged(self):
        assert _clamp("", 100) == ""

    def test_empty_string_at_zero_limit_unchanged(self):
        assert _clamp("", 0) == ""

    def test_one_over_limit_triggers_truncation(self):
        text = "x" * 101
        result = _clamp(text, 100)
        assert len(result) > 100  # truncated text + suffix message
        assert "101" in result

    def test_unicode_text_handled(self):
        # Chinese characters count as individual chars in len()
        text = "你好" * 100  # 200 chars
        result = _clamp(text, 50)
        assert "200" in result
        assert result[:50] == text[:50]

    def test_return_type_is_str(self):
        assert isinstance(_clamp("hello", 10), str)
        assert isinstance(_clamp("x" * 200, 10), str)


# ── Input validation constants ─────────────────────────────────────────────

class TestValidationConstants:
    def test_max_task_len_exists(self):
        assert isinstance(MAX_TASK_LEN, int)

    def test_max_error_text_len_exists(self):
        assert isinstance(MAX_ERROR_TEXT_LEN, int)

    def test_max_context_len_exists(self):
        assert isinstance(MAX_CONTEXT_LEN, int)

    def test_max_history_len_exists(self):
        assert isinstance(MAX_HISTORY_LEN, int)

    def test_max_trace_len_exists(self):
        assert isinstance(MAX_TRACE_LEN, int)

    def test_max_task_len_reasonable(self):
        # Task descriptions should be bounded but allow meaningful input
        assert 500 <= MAX_TASK_LEN <= 10_000

    def test_max_error_text_len_reasonable(self):
        # Error texts can be long (full tracebacks), but must be bounded
        assert 1_000 <= MAX_ERROR_TEXT_LEN <= 100_000

    def test_max_context_len_reasonable(self):
        # Context / directory trees can be large
        assert 10_000 <= MAX_CONTEXT_LEN <= 500_000

    def test_max_history_len_reasonable(self):
        # History JSON can be very large
        assert 10_000 <= MAX_HISTORY_LEN <= 1_000_000

    def test_max_trace_len_reasonable(self):
        # Trace JSON similar scale to context
        assert 10_000 <= MAX_TRACE_LEN <= 500_000

    def test_error_text_limit_larger_than_task_limit(self):
        # Error texts are typically longer than task descriptions
        assert MAX_ERROR_TEXT_LEN > MAX_TASK_LEN

    def test_context_limit_larger_than_error_text_limit(self):
        # Full project context is larger than a single error text
        assert MAX_CONTEXT_LEN > MAX_ERROR_TEXT_LEN

    def test_all_constants_positive(self):
        for name, val in [
            ("MAX_TASK_LEN", MAX_TASK_LEN),
            ("MAX_ERROR_TEXT_LEN", MAX_ERROR_TEXT_LEN),
            ("MAX_CONTEXT_LEN", MAX_CONTEXT_LEN),
            ("MAX_HISTORY_LEN", MAX_HISTORY_LEN),
            ("MAX_TRACE_LEN", MAX_TRACE_LEN),
        ]:
            assert val > 0, f"{name} must be positive"
