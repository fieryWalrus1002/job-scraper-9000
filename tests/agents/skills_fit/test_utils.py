"""Tests for skills_fit utils — profile formatting and client validation."""

import pytest

from agents.skills_fit.utils import _format_profile_block, _get_client, _to_list


class TestToList:
    def test_list_passthrough(self):
        assert _to_list(["a", "b"]) == ["a", "b"]

    def test_none_returns_empty(self):
        assert _to_list(None) == []

    def test_scalar_string_wraps(self):
        assert _to_list("Python") == ["Python"]

    def test_scalar_int_wraps(self):
        assert _to_list(42) == ["42"]


class TestFormatProfileBlock:
    def test_list_fields_join_correctly(self):
        profile = {
            "core_skills": ["Python", "C++"],
            "adjacent_skills": ["Docker"],
        }
        block = _format_profile_block(profile)
        assert "Python, C++" in block
        assert "Docker" in block

    def test_scalar_string_field_does_not_explode(self):
        # A single-item field written as a scalar in YAML would previously
        # cause join() to iterate characters and produce garbage.
        profile = {"core_skills": "Python"}
        block = _format_profile_block(profile)
        assert "Python" in block
        assert "y, t, h" not in block  # character-join garbage

    def test_none_field_omitted(self):
        block = _format_profile_block({"core_skills": None})
        assert "Core skills" not in block

    def test_missing_field_omitted(self):
        block = _format_profile_block({})
        assert "Core skills" not in block


class TestGetClient:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
            _get_client({"provider": "openai"})

    def test_custom_api_key_env_used(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("MY_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="MY_KEY"):
            _get_client({"provider": "openai", "api_key_env": "MY_KEY"})

    def test_valid_api_key_returns_client(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        client, model = _get_client({"provider": "openai", "model": "gpt-4o-mini"})
        assert model == "gpt-4o-mini"
        assert client is not None

    def test_ollama_skips_key_check(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client, model = _get_client({"provider": "ollama"})
        assert client is not None
