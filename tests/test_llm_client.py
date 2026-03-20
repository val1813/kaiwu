"""Tests for kaiwu.llm_client — _is_retryable, _check_circuit_breaker,
_record_success, _record_failure, record_usage, record_local_hit."""

import json
import time
from pathlib import Path

import pytest

import kaiwu.llm_client as llm_client
from kaiwu.llm_client import (
    _is_retryable,
    _check_circuit_breaker,
    _record_success,
    _record_failure,
    record_usage,
    record_local_hit,
    _circuit_breaker,
    _CB_THRESHOLD,
    _CB_COOLDOWN,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _reset_cb(monkeypatch):
    """Reset circuit breaker state to fresh via monkeypatch."""
    monkeypatch.setitem(_circuit_breaker, "consecutive_failures", 0)
    monkeypatch.setitem(_circuit_breaker, "open_until", 0.0)


# ── _is_retryable ──────────────────────────────────────────────────────────

class TestIsRetryable:
    def test_timeout_error_retryable(self):
        assert _is_retryable(Exception("Request timeout after 30s")) is True

    def test_timed_out_retryable(self):
        assert _is_retryable(Exception("Connection timed out")) is True

    def test_connection_error_retryable(self):
        assert _is_retryable(Exception("connection refused")) is True

    def test_connect_error_retryable(self):
        assert _is_retryable(Exception("Failed to connect to host")) is True

    def test_429_retryable(self):
        assert _is_retryable(Exception("HTTP 429 rate limit exceeded")) is True

    def test_502_retryable(self):
        assert _is_retryable(Exception("502 Bad Gateway")) is True

    def test_503_retryable(self):
        assert _is_retryable(Exception("503 Service Unavailable")) is True

    def test_rate_limit_retryable(self):
        assert _is_retryable(Exception("Rate limit reached")) is True

    def test_overloaded_retryable(self):
        assert _is_retryable(Exception("Model is overloaded")) is True

    def test_server_error_retryable(self):
        assert _is_retryable(Exception("internal server error")) is True

    def test_authentication_error_not_retryable(self):
        assert _is_retryable(Exception("401 Unauthorized: invalid API key")) is False

    def test_invalid_request_not_retryable(self):
        assert _is_retryable(Exception("Invalid request: max_tokens too large")) is False

    def test_random_error_not_retryable(self):
        assert _is_retryable(ValueError("something went wrong")) is False

    def test_empty_error_not_retryable(self):
        assert _is_retryable(Exception("")) is False

    def test_case_insensitive(self):
        assert _is_retryable(Exception("TIMEOUT")) is True


# ── _check_circuit_breaker ─────────────────────────────────────────────────

class TestCheckCircuitBreaker:
    def test_fresh_state_not_open(self, monkeypatch):
        _reset_cb(monkeypatch)
        is_open, msg = _check_circuit_breaker()
        assert is_open is False
        assert msg == ""

    def test_open_until_future_returns_true(self, monkeypatch):
        _reset_cb(monkeypatch)
        monkeypatch.setitem(_circuit_breaker, "open_until", time.time() + 60)
        is_open, msg = _check_circuit_breaker()
        assert is_open is True
        assert len(msg) > 0

    def test_open_message_contains_remaining_seconds(self, monkeypatch):
        _reset_cb(monkeypatch)
        monkeypatch.setitem(_circuit_breaker, "open_until", time.time() + 45)
        _, msg = _check_circuit_breaker()
        assert any(c.isdigit() for c in msg)

    def test_expired_cooldown_resets_to_closed(self, monkeypatch):
        _reset_cb(monkeypatch)
        monkeypatch.setitem(_circuit_breaker, "open_until", time.time() - 1)
        monkeypatch.setitem(_circuit_breaker, "consecutive_failures", 5)
        is_open, msg = _check_circuit_breaker()
        assert is_open is False
        assert msg == ""
        assert _circuit_breaker["open_until"] == 0.0
        assert _circuit_breaker["consecutive_failures"] == 0

    def test_zero_open_until_not_open(self, monkeypatch):
        _reset_cb(monkeypatch)
        monkeypatch.setitem(_circuit_breaker, "open_until", 0.0)
        is_open, _ = _check_circuit_breaker()
        assert is_open is False


# ── _record_success ────────────────────────────────────────────────────────

class TestRecordSuccess:
    def test_resets_consecutive_failures(self, monkeypatch):
        _reset_cb(monkeypatch)
        monkeypatch.setitem(_circuit_breaker, "consecutive_failures", 3)
        _record_success()
        assert _circuit_breaker["consecutive_failures"] == 0

    def test_resets_open_until(self, monkeypatch):
        _reset_cb(monkeypatch)
        monkeypatch.setitem(_circuit_breaker, "open_until", time.time() + 60)
        _record_success()
        assert _circuit_breaker["open_until"] == 0.0

    def test_idempotent_on_fresh_state(self, monkeypatch):
        _reset_cb(monkeypatch)
        _record_success()
        assert _circuit_breaker["consecutive_failures"] == 0
        assert _circuit_breaker["open_until"] == 0.0


# ── _record_failure ────────────────────────────────────────────────────────

class TestRecordFailure:
    def test_increments_counter(self, monkeypatch):
        _reset_cb(monkeypatch)
        _record_failure()
        assert _circuit_breaker["consecutive_failures"] == 1

    def test_multiple_failures_accumulate(self, monkeypatch):
        _reset_cb(monkeypatch)
        for _ in range(3):
            _record_failure()
        assert _circuit_breaker["consecutive_failures"] == 3

    def test_triggers_at_threshold(self, monkeypatch):
        _reset_cb(monkeypatch)
        for _ in range(_CB_THRESHOLD):
            _record_failure()
        assert _circuit_breaker["consecutive_failures"] >= _CB_THRESHOLD
        assert _circuit_breaker["open_until"] > time.time()

    def test_open_until_is_approximately_cooldown(self, monkeypatch):
        _reset_cb(monkeypatch)
        before = time.time()
        for _ in range(_CB_THRESHOLD):
            _record_failure()
        after = time.time()
        open_until = _circuit_breaker["open_until"]
        assert open_until >= before + _CB_COOLDOWN - 1
        assert open_until <= after + _CB_COOLDOWN + 1

    def test_below_threshold_does_not_open(self, monkeypatch):
        _reset_cb(monkeypatch)
        for _ in range(_CB_THRESHOLD - 1):
            _record_failure()
        assert _circuit_breaker["open_until"] == 0.0


# ── record_usage ───────────────────────────────────────────────────────────

class TestRecordUsage:
    def test_writes_to_file(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "usage.json"
        monkeypatch.setattr(llm_client, "USAGE_PATH", usage_file)

        record_usage(100, 50, purpose="test")

        assert usage_file.exists()
        data = json.loads(usage_file.read_text(encoding="utf-8"))
        assert data["total_prompt_tokens"] == 100
        assert data["total_completion_tokens"] == 50
        assert data["total_calls"] == 1

    def test_accumulates_on_multiple_calls(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "usage.json"
        monkeypatch.setattr(llm_client, "USAGE_PATH", usage_file)

        record_usage(100, 50)
        record_usage(200, 75)

        data = json.loads(usage_file.read_text(encoding="utf-8"))
        assert data["total_prompt_tokens"] == 300
        assert data["total_completion_tokens"] == 125
        assert data["total_calls"] == 2

    def test_daily_bucket_written(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "usage.json"
        monkeypatch.setattr(llm_client, "USAGE_PATH", usage_file)
        today = time.strftime("%Y-%m-%d")

        record_usage(10, 5)

        data = json.loads(usage_file.read_text(encoding="utf-8"))
        assert today in data["daily"]
        day = data["daily"][today]
        assert day["prompt_tokens"] == 10
        assert day["completion_tokens"] == 5
        assert day["calls"] == 1

    def test_by_purpose_tracked(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "usage.json"
        monkeypatch.setattr(llm_client, "USAGE_PATH", usage_file)

        record_usage(30, 20, purpose="plan")

        data = json.loads(usage_file.read_text(encoding="utf-8"))
        assert "by_purpose" in data
        assert "plan" in data["by_purpose"]
        assert data["by_purpose"]["plan"]["calls"] == 1
        assert data["by_purpose"]["plan"]["tokens"] == 50

    def test_no_purpose_no_by_purpose_key(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "usage.json"
        monkeypatch.setattr(llm_client, "USAGE_PATH", usage_file)

        record_usage(10, 5, purpose="")

        data = json.loads(usage_file.read_text(encoding="utf-8"))
        assert "by_purpose" not in data

    def test_local_hits_initialized(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "usage.json"
        monkeypatch.setattr(llm_client, "USAGE_PATH", usage_file)

        record_usage(1, 1)

        data = json.loads(usage_file.read_text(encoding="utf-8"))
        assert "local_hits" in data
        assert data["local_hits"] == 0

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "subdir" / "usage.json"
        monkeypatch.setattr(llm_client, "USAGE_PATH", usage_file)

        record_usage(1, 1)

        assert usage_file.exists()

    def test_corrupted_existing_file_recovered(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "usage.json"
        usage_file.write_text("NOT JSON", encoding="utf-8")
        monkeypatch.setattr(llm_client, "USAGE_PATH", usage_file)

        record_usage(5, 5)

        data = json.loads(usage_file.read_text(encoding="utf-8"))
        assert data["total_calls"] == 1


# ── record_local_hit ───────────────────────────────────────────────────────

class TestRecordLocalHit:
    def test_increments_local_hits(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "usage.json"
        monkeypatch.setattr(llm_client, "USAGE_PATH", usage_file)

        record_local_hit()

        data = json.loads(usage_file.read_text(encoding="utf-8"))
        assert data["local_hits"] == 1

    def test_multiple_hits_accumulate(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "usage.json"
        monkeypatch.setattr(llm_client, "USAGE_PATH", usage_file)

        record_local_hit()
        record_local_hit()
        record_local_hit()

        data = json.loads(usage_file.read_text(encoding="utf-8"))
        assert data["local_hits"] == 3

    def test_daily_local_hits_tracked(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "usage.json"
        monkeypatch.setattr(llm_client, "USAGE_PATH", usage_file)
        today = time.strftime("%Y-%m-%d")

        record_local_hit()
        record_local_hit()

        data = json.loads(usage_file.read_text(encoding="utf-8"))
        assert data["daily"][today]["local_hits"] == 2

    def test_does_not_affect_total_calls(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "usage.json"
        monkeypatch.setattr(llm_client, "USAGE_PATH", usage_file)

        record_local_hit()

        data = json.loads(usage_file.read_text(encoding="utf-8"))
        assert data.get("total_calls", 0) == 0

    def test_does_not_affect_total_tokens(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "usage.json"
        monkeypatch.setattr(llm_client, "USAGE_PATH", usage_file)

        record_local_hit()

        data = json.loads(usage_file.read_text(encoding="utf-8"))
        assert data.get("total_prompt_tokens", 0) == 0
        assert data.get("total_completion_tokens", 0) == 0
