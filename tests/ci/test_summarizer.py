"""Tests for PRSummarizer."""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_CONFIG = """
llm:
  provider: openai
  model: gpt-4o-mini
  temperature: 0.2
  max_tokens: 512
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
# Config and prompt loading
# ---------------------------------------------------------------------------


def test_loads_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from ci.summarizer import PRSummarizer
    with patch("ci.summarizer.OpenAI"):
        s = PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path))
    assert s.config["llm"]["model"] == "gpt-4o-mini"
    assert s.config["llm"]["temperature"] == 0.2


def test_strips_frontmatter_from_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from ci.summarizer import PRSummarizer
    with patch("ci.summarizer.OpenAI"):
        s = PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path))
    assert "---" not in s.system_prompt
    assert "You are a helpful assistant." in s.system_prompt


def test_prompt_without_frontmatter_passes_through(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from ci.summarizer import PRSummarizer
    with patch("ci.summarizer.OpenAI"):
        s = PRSummarizer(
            _write_config(tmp_path),
            _write_prompt(tmp_path, PROMPT_WITHOUT_FRONTMATTER),
        )
    assert s.system_prompt == PROMPT_WITHOUT_FRONTMATTER


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------


def test_missing_api_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    from ci.summarizer import PRSummarizer
    # patch load_dotenv so the real .env doesn't re-inject the key
    with patch("ci.summarizer.load_dotenv"), pytest.raises(ValueError, match="OPENAI_API_KEY"):
        PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path))


def test_generate_returns_content(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from ci.summarizer import PRSummarizer
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_completion("Great PR!")
    with patch("ci.summarizer.OpenAI", return_value=mock_client):
        s = PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path))
    assert s.generate("some diff") == "Great PR!"


def test_generate_passes_correct_params(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from ci.summarizer import PRSummarizer
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_completion("ok")
    with patch("ci.summarizer.OpenAI", return_value=mock_client):
        s = PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path))
    s.generate("diff content")
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["max_tokens"] == 512


def test_generate_raises_on_empty_response(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from ci.summarizer import PRSummarizer
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_completion("")
    with patch("ci.summarizer.OpenAI", return_value=mock_client):
        s = PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path))
    with pytest.raises(ValueError, match="empty response"):
        s.generate("diff")


# ---------------------------------------------------------------------------
# Ollama provider
# ---------------------------------------------------------------------------


def test_ollama_provider_does_not_require_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    from ci.summarizer import PRSummarizer
    with patch("ci.summarizer.OpenAI") as mock_openai:
        PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path))
    mock_openai.assert_called_once_with(
        base_url="http://localhost:11434/v1", api_key="ollama"
    )


def test_ollama_uses_default_base_url_when_not_set(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    from ci.summarizer import PRSummarizer
    with patch("ci.summarizer.OpenAI") as mock_openai:
        PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path))
    mock_openai.assert_called_once_with(
        base_url="http://localhost:11434/v1", api_key="ollama"
    )


# ---------------------------------------------------------------------------
# LLM_MODEL env override
# ---------------------------------------------------------------------------


def test_llm_model_env_overrides_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o")
    from ci.summarizer import PRSummarizer
    with patch("ci.summarizer.OpenAI"):
        s = PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path))
    assert s.config["llm"]["model"] == "gpt-4o"


def test_llm_model_env_used_in_api_call(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o")
    from ci.summarizer import PRSummarizer
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_completion("ok")
    with patch("ci.summarizer.OpenAI", return_value=mock_client):
        s = PRSummarizer(_write_config(tmp_path), _write_prompt(tmp_path))
    s.generate("diff")
    assert mock_client.chat.completions.create.call_args.kwargs["model"] == "gpt-4o"
