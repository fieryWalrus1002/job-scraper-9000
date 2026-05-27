"""Tests for PRSummarizer and build_client_from_env."""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

MINIMAL_CONFIG = """
llm:
  provider: openai
  model: gpt-4o-mini
  temperature: 0.2
  max_tokens: 512
"""

MINIMAL_CONFIG_OLLAMA = """
llm:
  provider: ollama
  model: qwen2.5:14b
  temperature: 0.2
  max_tokens: 512
  ollama_base_url: http://localhost:11434/v1
"""

PROMPT_WITH_FRONTMATTER = """\
---
template_name: test
version: 1.0.0
---

You are a helpful assistant.
"""

PROMPT_WITHOUT_FRONTMATTER = "You are a helpful assistant."


def _write_config(tmp_path, content=MINIMAL_CONFIG):
    p = tmp_path / "config.yml"
    p.write_text(content)
    return str(p)


def _write_prompt(tmp_path, content=PROMPT_WITH_FRONTMATTER):
    p = tmp_path / "prompt.md"
    p.write_text(content)
    return str(p)


def _make_completion(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ---------------------------------------------------------------------------
# PRSummarizer — config and prompt loading (no env manipulation needed)
# ---------------------------------------------------------------------------


def test_loads_config(tmp_path):
    from ci.summarizer import PRSummarizer

    s = PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path), MagicMock())
    assert s.config["llm"]["model"] == "gpt-4o-mini"
    assert s.config["llm"]["temperature"] == 0.2


def test_strips_frontmatter_from_prompt(tmp_path):
    from ci.summarizer import PRSummarizer

    s = PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path), MagicMock())
    assert "---" not in s.system_prompt
    assert "You are a helpful assistant." in s.system_prompt


def test_prompt_without_frontmatter_passes_through(tmp_path):
    from ci.summarizer import PRSummarizer

    s = PRSummarizer(
        _write_config(tmp_path),
        _write_prompt(tmp_path, PROMPT_WITHOUT_FRONTMATTER),
        MagicMock(),
    )
    assert s.system_prompt == PROMPT_WITHOUT_FRONTMATTER


# ---------------------------------------------------------------------------
# PRSummarizer — generate()
# ---------------------------------------------------------------------------


def test_generate_returns_content(tmp_path):
    from ci.summarizer import PRSummarizer

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_completion("Great PR!")
    s = PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path), mock_client)
    assert s.generate("some diff") == "Great PR!"


def test_generate_passes_correct_params(tmp_path):
    from ci.summarizer import PRSummarizer

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_completion("ok")
    s = PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path), mock_client)
    s.generate("diff content")
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["max_tokens"] == 512


def test_generate_raises_on_empty_response(tmp_path):
    from ci.summarizer import PRSummarizer

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_completion("")
    s = PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path), mock_client)
    with pytest.raises(ValueError, match="empty response"):
        s.generate("diff")


# ---------------------------------------------------------------------------
# build_client_from_env — OpenAI provider
# ---------------------------------------------------------------------------


def test_missing_api_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from ci.summarizer import build_client_from_env

    with (
        patch("ci.summarizer.load_dotenv"),
        pytest.raises(ValueError, match="OPENAI_API_KEY"),
    ):
        build_client_from_env(_write_config(tmp_path))


def test_openai_client_built_with_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from ci.summarizer import build_client_from_env

    with (
        patch("ci.summarizer.load_dotenv"),
        patch("ci.summarizer.OpenAI") as mock_openai,
    ):
        build_client_from_env(_write_config(tmp_path))
    mock_openai.assert_called_once_with(api_key="test-key")


# ---------------------------------------------------------------------------
# build_client_from_env — Ollama provider
# ---------------------------------------------------------------------------


def test_ollama_provider_does_not_require_api_key(tmp_path):
    from ci.summarizer import build_client_from_env

    with (
        patch("ci.summarizer.load_dotenv"),
        patch("ci.summarizer.OpenAI") as mock_openai,
    ):
        build_client_from_env(_write_config(tmp_path, MINIMAL_CONFIG_OLLAMA))
    mock_openai.assert_called_once_with(
        base_url="http://localhost:11434/v1", api_key="ollama"
    )


def test_ollama_uses_default_base_url_when_not_in_config(tmp_path):
    config_no_url = """
llm:
  provider: ollama
  model: qwen2.5:14b
  temperature: 0.2
  max_tokens: 512
"""
    from ci.summarizer import build_client_from_env

    with (
        patch("ci.summarizer.load_dotenv"),
        patch("ci.summarizer.OpenAI") as mock_openai,
    ):
        build_client_from_env(_write_config(tmp_path, config_no_url))
    mock_openai.assert_called_once_with(
        base_url="http://localhost:11434/v1", api_key="ollama"
    )
