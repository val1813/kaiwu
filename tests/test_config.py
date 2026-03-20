"""配置模块单元测试"""

import sys
import pytest

import kaiwu.config as config_module
from kaiwu.config import (
    _toml_value,
    infer_host_level,
    is_same_family,
    Config,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
)


# ── _toml_value ───────────────────────────────────────────────────

def test_toml_value_str_normal():
    assert _toml_value("hello") == '"hello"'


def test_toml_value_str_with_quotes():
    assert _toml_value('say "hi"') == '"say \\"hi\\""'


def test_toml_value_str_with_backslash():
    assert _toml_value("C:\\Users") == '"C:\\\\Users"'


def test_toml_value_str_empty():
    assert _toml_value("") == '""'


def test_toml_value_bool_true():
    assert _toml_value(True) == "true"


def test_toml_value_bool_false():
    assert _toml_value(False) == "false"


def test_toml_value_int():
    assert _toml_value(42) == "42"


def test_toml_value_float():
    assert _toml_value(3.14) == "3.14"


def test_toml_value_none():
    assert _toml_value(None) == '""'


def test_toml_value_list_empty():
    assert _toml_value([]) == "[]"


def test_toml_value_list_strings():
    assert _toml_value(["a", "b"]) == '["a", "b"]'


def test_toml_value_list_mixed_types():
    result = _toml_value(["hello", 1, True])
    assert result == '["hello", 1, true]'


def test_toml_value_list_nested_escaping():
    result = _toml_value(['path\\to'])
    assert result == '["path\\\\to"]'


# ── infer_host_level ──────────────────────────────────────────────

def test_infer_host_level_explicit_strong():
    assert infer_host_level(host_level="strong") == "strong"


def test_infer_host_level_explicit_medium():
    assert infer_host_level(host_level="medium") == "medium"


def test_infer_host_level_explicit_weak():
    assert infer_host_level(host_level="weak") == "weak"


def test_infer_host_level_explicit_overrides_model():
    # explicit level takes priority regardless of model name
    assert infer_host_level(host_level="strong", host_model="haiku") == "strong"


def test_infer_host_level_empty_both():
    assert infer_host_level() == "weak"


def test_infer_host_level_empty_host_level_no_model():
    assert infer_host_level(host_level="", host_model="") == "weak"


def test_infer_host_level_invalid_host_level_falls_through():
    # invalid value is not in (strong/medium/weak) → infers from model
    assert infer_host_level(host_level="ultra", host_model="") == "weak"


# model → strong
def test_infer_host_level_model_opus():
    assert infer_host_level(host_model="claude-opus-4-6") == "strong"


def test_infer_host_level_model_sonnet():
    assert infer_host_level(host_model="claude-sonnet-4-20250514") == "strong"


def test_infer_host_level_model_gpt4o():
    assert infer_host_level(host_model="gpt-4o") == "strong"


def test_infer_host_level_model_gpt4_turbo():
    assert infer_host_level(host_model="gpt-4-turbo") == "strong"


def test_infer_host_level_model_gpt41():
    assert infer_host_level(host_model="gpt-4.1") == "strong"


def test_infer_host_level_model_deepseek_r1():
    assert infer_host_level(host_model="deepseek-r1") == "strong"


# model → weak
def test_infer_host_level_model_haiku():
    assert infer_host_level(host_model="claude-haiku-3") == "weak"


def test_infer_host_level_model_flash():
    assert infer_host_level(host_model="gemini-2.0-flash") == "weak"


def test_infer_host_level_model_gpt35():
    assert infer_host_level(host_model="gpt-3.5-turbo") == "weak"


def test_infer_host_level_model_small_param():
    assert infer_host_level(host_model="llama-8b") == "weak"


def test_infer_host_level_model_lite():
    assert infer_host_level(host_model="some-model-lite") == "weak"


# conflict: o4-mini has both strong (o4-) and weak (mini) → weak wins
def test_infer_host_level_model_o4_mini_conflict():
    assert infer_host_level(host_model="o4-mini") == "weak"


# gemini should NOT be treated as weak (gemini contains "mini" within "gemini" but excluded)
def test_infer_host_level_model_gemini2_not_weak():
    assert infer_host_level(host_model="gemini-2-pro") == "strong"


# model → medium (unknown / ambiguous)
def test_infer_host_level_model_unknown():
    assert infer_host_level(host_model="some-unknown-model") == "medium"


def test_infer_host_level_model_deepseek_chat():
    # deepseek-chat has no strong/weak marker → medium
    assert infer_host_level(host_model="deepseek-chat") == "medium"


# ── is_same_family ────────────────────────────────────────────────

def test_is_same_family_same_vendor():
    assert is_same_family("deepseek-chat", "deepseek-r1") is True


def test_is_same_family_different_vendor():
    assert is_same_family("deepseek-chat", "openai-gpt4") is False


def test_is_same_family_empty_host():
    assert is_same_family("", "deepseek-r1") is False


def test_is_same_family_empty_backend():
    assert is_same_family("deepseek-chat", "") is False


def test_is_same_family_both_empty():
    assert is_same_family("", "") is False


def test_is_same_family_claude_variants():
    assert is_same_family("claude-opus-4", "claude-sonnet-3") is True


def test_is_same_family_underscore_separator():
    assert is_same_family("gpt_4o", "gpt_35_turbo") is True


def test_is_same_family_no_separator_same():
    # no separator → full string is vendor
    assert is_same_family("llama", "llama") is True


def test_is_same_family_no_separator_different():
    assert is_same_family("llama", "mistral") is False


# ── Config.get ────────────────────────────────────────────────────

def test_config_get_top_level(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.toml")
    cfg = Config()
    cfg._data = {"active_provider": "deepseek"}
    assert cfg.get("active_provider") == "deepseek"


def test_config_get_dot_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.toml")
    cfg = Config()
    cfg._data = {"providers": {"deepseek": {"api_key": "sk-test"}}}
    assert cfg.get("providers.deepseek.api_key") == "sk-test"


def test_config_get_missing_key_returns_default(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.toml")
    cfg = Config()
    cfg._data = {}
    assert cfg.get("nonexistent.key", "fallback") == "fallback"


def test_config_get_missing_key_default_none(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.toml")
    cfg = Config()
    cfg._data = {}
    assert cfg.get("missing") is None


def test_config_get_partial_path_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.toml")
    cfg = Config()
    cfg._data = {"providers": {}}
    assert cfg.get("providers.deepseek.api_key", "none") == "none"


# ── Config.set ────────────────────────────────────────────────────

def test_config_set_creates_nested(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(config_module, "KAIWU_HOME", tmp_path)
    cfg = Config()
    cfg._data = {}
    cfg.set("providers.openai.api_key", "sk-openai")
    assert cfg._data["providers"]["openai"]["api_key"] == "sk-openai"


def test_config_set_top_level(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(config_module, "KAIWU_HOME", tmp_path)
    cfg = Config()
    cfg._data = {}
    cfg.set("active_provider", "openai")
    assert cfg._data["active_provider"] == "openai"


def test_config_set_persists_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(config_module, "KAIWU_HOME", tmp_path)
    cfg = Config()
    cfg._data = {}
    cfg.set("active_provider", "openai")
    assert (tmp_path / "config.toml").exists()


# ── Config._migrate_legacy ────────────────────────────────────────

def test_migrate_legacy_moves_deepseek_section(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(config_module, "KAIWU_HOME", tmp_path)
    cfg = Config()
    cfg._data = {
        "deepseek": {
            "api_key": "sk-old",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
        }
    }
    cfg._migrate_legacy()
    assert "deepseek" not in cfg._data
    assert cfg._data["providers"]["deepseek"]["api_key"] == "sk-old"
    assert cfg._data["providers"]["deepseek"]["api_format"] == "openai"


def test_migrate_legacy_sets_active_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(config_module, "KAIWU_HOME", tmp_path)
    cfg = Config()
    cfg._data = {"deepseek": {"api_key": "sk-old"}}
    cfg._migrate_legacy()
    assert cfg._data.get("active_provider") == "deepseek"


def test_migrate_legacy_skips_if_no_deepseek(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.toml")
    cfg = Config()
    cfg._data = {"active_provider": "openai"}
    cfg._migrate_legacy()
    assert cfg._data == {"active_provider": "openai"}


def test_migrate_legacy_skips_if_providers_deepseek_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.toml")
    cfg = Config()
    cfg._data = {
        "deepseek": {"api_key": "sk-old"},
        "providers": {"deepseek": {"api_key": "sk-new"}},
    }
    cfg._migrate_legacy()
    # old key should remain untouched, providers.deepseek keeps new value
    assert cfg._data["providers"]["deepseek"]["api_key"] == "sk-new"


def test_migrate_legacy_uses_defaults_for_missing_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(config_module, "KAIWU_HOME", tmp_path)
    cfg = Config()
    cfg._data = {"deepseek": {"api_key": "sk-only"}}
    cfg._migrate_legacy()
    provider = cfg._data["providers"]["deepseek"]
    assert provider["base_url"] == DEFAULT_DEEPSEEK_BASE_URL
    assert provider["model"] == DEFAULT_DEEPSEEK_MODEL


# ── Config loads from real TOML file ─────────────────────────────

def test_config_loads_toml_file(tmp_path, monkeypatch):
    toml_content = b'[providers.deepseek]\napi_key = "sk-fromfile"\nmodel = "deepseek-chat"\n'
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_bytes(toml_content)
    monkeypatch.setattr(config_module, "CONFIG_PATH", cfg_path)
    cfg = Config()
    assert cfg.get("providers.deepseek.api_key") == "sk-fromfile"


def test_config_missing_file_gives_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "nonexistent.toml")
    cfg = Config()
    assert cfg._data == {}


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
