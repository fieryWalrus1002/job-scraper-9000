import pytest

from agents.remote_filter.utils import _get_client, resolve_llm_model


@pytest.mark.parametrize(
    "cfg, env, expected",
    [
        ({"provider": "openai", "model": "gpt-explicit"}, {}, "gpt-explicit"),
        ({"provider": "ollama", "model": "qwen-explicit"}, {}, "qwen-explicit"),
        ({"provider": "openai"}, {}, "gpt-4o-mini"),
        ({"provider": "ollama"}, {}, "qwen2.5:14b"),
        ({"provider": "openai"}, {"LLM_MODEL": "env-model"}, "env-model"),
        ({"provider": "ollama"}, {"LLM_MODEL": "env-ollama"}, "env-ollama"),
        (None, {}, "gpt-4o-mini"),
        ({}, {"LLM_PROVIDER": "ollama"}, "qwen2.5:14b"),
    ],
    ids=[
        "openai-explicit",
        "ollama-explicit",
        "openai-default",
        "ollama-default",
        "openai-env-override",
        "ollama-env-override",
        "all-defaults",
        "env-provider-only",
    ],
)
def test_get_client_and_resolve_llm_model_agree(cfg, env, expected, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-for-client-init")
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    _, client_model = _get_client(cfg)
    helper_model = resolve_llm_model(cfg)

    assert client_model == helper_model == expected
