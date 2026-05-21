import pytest

from agents.remote_filter.utils import (
    _get_client,
    context_fingerprint,
    resolve_llm_model,
)


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


# ---------------------------------------------------------------------------
# context_fingerprint
# ---------------------------------------------------------------------------


def test_context_fingerprint_none_for_empty_inputs():
    assert context_fingerprint(None) == "none"
    assert context_fingerprint({}) == "none"
    # All-falsy values fingerprint identically to "no relevant context".
    assert context_fingerprint({"keywords": "", "user_timezone": None}) == "none"


def test_context_fingerprint_changes_with_relevant_field():
    base = {"keywords": "AI", "user_timezone": "PST"}
    assert context_fingerprint(base) != context_fingerprint(
        {"keywords": "AI", "user_timezone": "EST"}
    )
    assert context_fingerprint(base) != context_fingerprint({"keywords": "ML", "user_timezone": "PST"})


def test_context_fingerprint_stable_for_irrelevant_field():
    # Fields not read by `_build_user_message` must not affect the cache key.
    fp1 = context_fingerprint({"keywords": "AI"})
    fp2 = context_fingerprint({"keywords": "AI", "country": "USA", "noise": 42})
    assert fp1 == fp2


def test_context_fingerprint_stable_across_key_ordering():
    fp1 = context_fingerprint({"keywords": "AI", "workplace": "remote"})
    fp2 = context_fingerprint({"workplace": "remote", "keywords": "AI"})
    assert fp1 == fp2
