"""Unit tests for loading the VA API key from a .env file."""

import pytest

from va_resources_mcp.config import API_KEY_VAR, ConfigError, load_api_key


@pytest.fixture(autouse=True)
def no_key_in_environment(monkeypatch):
    # setenv first so monkeypatch records the real value (or its absence) and restores it
    # afterwards, including undoing whatever load_dotenv sets during the test.
    monkeypatch.setenv(API_KEY_VAR, "placeholder")
    monkeypatch.delenv(API_KEY_VAR)


def env_file(tmp_path, content: str):
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    return path


def test_returns_key_from_env_file(tmp_path):
    assert load_api_key(env_file(tmp_path, "VA_API_KEY=from-file\n")) == "from-file"


def test_existing_environment_variable_wins_over_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv(API_KEY_VAR, "from-environment")
    assert load_api_key(env_file(tmp_path, "VA_API_KEY=from-file\n")) == "from-environment"


@pytest.mark.parametrize("content", ["VA_FORMS_API_KEY=other\n", None], ids=["absent", "no-file"])
def test_missing_key_raises_config_error_naming_env_example(tmp_path, content):
    path = env_file(tmp_path, content) if content is not None else tmp_path / ".env"
    with pytest.raises(ConfigError, match=r"VA_API_KEY is not set.*\.env\.example"):
        load_api_key(path)


@pytest.mark.parametrize("value", ["", "   "], ids=["empty", "whitespace"])
def test_blank_key_raises_config_error(tmp_path, value):
    with pytest.raises(ConfigError, match="VA_API_KEY is not set"):
        load_api_key(env_file(tmp_path, f'VA_API_KEY="{value}"\n'))
