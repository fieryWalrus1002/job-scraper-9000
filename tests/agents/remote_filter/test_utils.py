import pytest

from agents.remote_filter.input_models import RemoteFilterInput
from agents.remote_filter.utils import (
    _get_client,
    build_search_context,
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
# build_search_context
# ---------------------------------------------------------------------------


def test_build_search_context_canonicalizes_consolidated_search_contexts():
    contexts = [
        {"source": "linkedin", "workplace": "remote"},
        {"workplace": "remote", "source": "linkedin"},
        {"source": "workday", "source_detail_location": "Remote"},
    ]

    first = build_search_context({"search_contexts": contexts})
    second = build_search_context({"search_contexts": list(reversed(contexts))})

    assert first == second
    assert [context.to_prompt_dict() for context in first.search_contexts] == [
        {"source": "linkedin", "workplace": "remote"},
        {"source": "workday", "source_detail_location": "Remote"},
    ]


def test_build_search_context_drops_non_prompt_provenance_from_search_contexts():
    context = build_search_context(
        {
            "search_contexts": [
                {
                    "source": "workday",
                    "workplace": "remote",
                    "source_detail_location": "Remote; Washington, DC",
                    "workday_job_req_id": "JR100168",
                }
            ]
        }
    )

    assert [item.to_prompt_dict() for item in context.search_contexts] == [
        {
            "source": "workday",
            "workplace": "remote",
            "source_detail_location": "Remote; Washington, DC",
        }
    ]


def test_build_search_context_merges_consolidated_search_contexts():
    job = {
        "search_params": {"keywords": "data engineer"},
        "search_contexts": [
            {
                "source": "workday",
                "workplace": "remote",
                "job_type": "fulltime",
                "source_detail_location": "Remote; Washington, DC",
            }
        ],
    }

    context = build_search_context(job, user_timezone="PST")

    assert context.description == ""
    assert context.keywords == "data engineer"
    assert [item.to_prompt_dict() for item in context.search_contexts] == [
        {
            "source": "workday",
            "workplace": "remote",
            "job_type": "fulltime",
            "source_detail_location": "Remote; Washington, DC",
        }
    ]
    assert context.user_timezone == "PST"


# ---------------------------------------------------------------------------
# context_fingerprint
# ---------------------------------------------------------------------------


def test_context_fingerprint_none_for_empty_inputs():
    assert context_fingerprint(None) == "none"
    assert context_fingerprint(RemoteFilterInput(description="")) == "none"
    # All-falsy values fingerprint identically to "no relevant context".
    assert (
        context_fingerprint(
            RemoteFilterInput(description="", keywords="", user_timezone=None)
        )
        == "none"
    )


def test_context_fingerprint_changes_with_relevant_field():
    base = RemoteFilterInput(description="", keywords="AI", user_timezone="PST")
    assert context_fingerprint(base) != context_fingerprint(
        RemoteFilterInput(description="", keywords="AI", user_timezone="EST")
    )
    assert context_fingerprint(base) != context_fingerprint(
        RemoteFilterInput(description="", keywords="ML", user_timezone="PST")
    )


def test_context_fingerprint_stable_for_irrelevant_field():
    # Fields not read by `_build_user_message` must not affect the cache key.
    # Exercise the legacy Mapping boundary: extra keys the input contract never
    # models (country, noise) must be ignored, not fingerprinted.
    fp1 = context_fingerprint({"keywords": "AI"})
    fp2 = context_fingerprint({"keywords": "AI", "country": "USA", "noise": 42})
    assert fp1 == fp2


def test_context_fingerprint_stable_across_key_ordering():
    fp1 = context_fingerprint(
        RemoteFilterInput(description="", keywords="AI", workplace="remote")
    )
    fp2 = context_fingerprint(
        RemoteFilterInput(description="", workplace="remote", keywords="AI")
    )
    assert fp1 == fp2


def test_context_fingerprint_pins_known_input_hash():
    rf_input = RemoteFilterInput(
        description="",
        keywords="AI",
        workplace="remote",
        job_type="fulltime",
        user_timezone="PST",
        search_contexts=[
            {
                "source": "workday",
                "workplace": "remote",
                "job_type": "fulltime",
                "source_detail_location": "Remote; Washington, DC",
            }
        ],
    )

    assert context_fingerprint(rf_input) == "7fb8c32e"
