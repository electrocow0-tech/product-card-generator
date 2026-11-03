import pytest

from app import config


def test_empty_values_fall_back_to_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "load_env_files", lambda: None)
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("LLM_BASE_URL", " https://example.com/v1/ ")
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "")
    s = config.load_settings()
    assert s.model == "gpt-4.1-mini" and s.base_url == "https://example.com/v1" and s.max_attempts == 3


def test_missing_key_is_config_error(monkeypatch):
    monkeypatch.setattr(config, "load_env_files", lambda: None)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="LLM_API_KEY"):
        config.load_settings()


def test_env_dir_files_take_precedence_over_dotenv(monkeypatch, tmp_path):
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "local.env").write_text("LLM_API_KEY=from-env-dir\nLLM_MODEL=m1\n")
    (tmp_path / ".env").write_text("LLM_API_KEY=from-dotenv\nLLM_MODEL=m2\nLLM_TIMEOUT=7\n")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    for name in ("LLM_API_KEY", "LLM_MODEL", "LLM_TIMEOUT", "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    s = config.load_settings()
    assert s.api_key == "from-env-dir" and s.model == "m1" and s.timeout == 7
