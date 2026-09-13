"""
Tests for app.core.config.Settings.

Settings() picks up backend/.env if one exists (see SettingsConfigDict in
config.py) -- a developer running these tests with a real .env in place
would otherwise get non-deterministic results depending on what's in it.
Every test here passes `_env_file=None` (a pydantic-settings option) to
bypass that file and test against the hardcoded defaults / real OS
environment variables only, regardless of the machine it runs on.
"""

from app.core.config import Settings


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_settings_defaults():
    settings = _settings()

    assert settings.PROJECT_NAME == "Vecton AI Construction Compliance Assistant"
    assert settings.CORS_ORIGINS == ["*"]
    assert settings.EMBEDDING_PROVIDER == "gemini"
    assert settings.EMBEDDING_DIM == 768
    assert settings.LLM_PROVIDER == "gemini"
    assert settings.GEMINI_API_KEY == ""
    assert settings.PDF_PARSER == "llamaparse"
    assert settings.LLAMAPARSE_API_KEY == ""


def test_settings_can_be_overridden_by_constructor_kwargs():
    settings = _settings(GEMINI_API_KEY="test-key", EMBEDDING_DIM=1536)

    assert settings.GEMINI_API_KEY == "test-key"
    assert settings.EMBEDDING_DIM == 1536


def test_settings_can_be_overridden_by_environment_variables(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    monkeypatch.setenv("LLM_MODEL_NAME", "gemini-9000")

    settings = _settings()

    assert settings.GEMINI_API_KEY == "from-env"
    assert settings.LLM_MODEL_NAME == "gemini-9000"


def test_settings_embedding_dim_env_var_is_coerced_to_int(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIM", "512")

    assert _settings().EMBEDDING_DIM == 512


def test_settings_cors_origins_parsed_from_a_json_list_env_var(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:5173", "https://example.com"]')

    assert _settings().CORS_ORIGINS == ["http://localhost:5173", "https://example.com"]


def test_settings_ignores_unrelated_environment_variables(monkeypatch):
    # model_config sets extra="ignore" -- an unrelated env var must not
    # raise, unlike pydantic-settings' default ("forbid").
    monkeypatch.setenv("SOME_UNRELATED_VARIABLE", "whatever")

    settings = _settings()

    assert not hasattr(settings, "SOME_UNRELATED_VARIABLE")


def test_settings_is_a_module_level_singleton():
    from app.core.config import settings

    assert isinstance(settings, Settings)
