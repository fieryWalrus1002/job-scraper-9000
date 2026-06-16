"""Tests for the AI code-review CI helper."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

MINIMAL_CONFIG = """
llm:
  provider: openai
  model: gpt-5.4-mini
  temperature: 0.2
  max_tokens: 1600
max_diff_chars: 20
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

Review this diff.
"""


def _write_config(tmp_path, content=MINIMAL_CONFIG):
    path = tmp_path / "config.yml"
    path.write_text(content)
    return str(path)


def _write_prompt(tmp_path, content=PROMPT_WITH_FRONTMATTER):
    path = tmp_path / "prompt.md"
    path.write_text(content)
    return str(path)


def _make_completion(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def test_parse_pr_metadata_handles_null_comment_shapes():
    from ci.ai_review import parse_pr_metadata

    metadata = parse_pr_metadata(
        {
            "title": None,
            "body": None,
            "milestone": None,
            "comments": [
                {"author": None, "body": " useful context "},
                {"author": {"login": "octo"}, "body": None},
                {"author": {"login": "bot"}, "body": ""},
            ],
        }
    )

    assert metadata.title == "Unknown Title"
    assert metadata.body == "No description provided."
    assert metadata.milestone == "None"
    assert metadata.comments == ("- unknown: useful context",)


def test_fetch_pr_metadata_passes_pr_to_gh_and_parses_response():
    from ci.ai_review import fetch_pr_metadata

    def fake_runner(cmd, **kwargs):
        assert cmd == [
            "gh",
            "pr",
            "view",
            "269",
            "--json",
            "title,body,milestone,comments",
        ]
        assert kwargs == {"capture_output": True, "text": True, "check": True}
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "title": "PR title",
                    "body": "PR body",
                    "milestone": {"title": "Phase X"},
                    "comments": [],
                }
            ),
        )

    metadata = fetch_pr_metadata("269", runner=fake_runner)

    assert metadata.title == "PR title"
    assert metadata.body == "PR body"
    assert metadata.milestone == "Phase X"


def test_load_pr_metadata_from_file_parses_gh_json(tmp_path):
    from ci.ai_review import load_pr_metadata_from_file

    meta_file = tmp_path / "pr_meta.json"
    meta_file.write_text(
        json.dumps(
            {
                "title": "PR title",
                "body": "PR body",
                "milestone": {"title": "Phase X"},
                "comments": [{"author": {"login": "octo"}, "body": "ship it"}],
            }
        )
    )

    metadata = load_pr_metadata_from_file(str(meta_file))

    assert metadata.title == "PR title"
    assert metadata.milestone == "Phase X"
    assert metadata.comments == ("- octo: ship it",)


def test_fetch_pr_metadata_fails_loudly_on_gh_error():
    from ci.ai_review import fetch_pr_metadata

    def fake_runner(*_args, **_kwargs):
        raise subprocess.CalledProcessError(2, ["gh"], stderr="auth failed")

    with pytest.raises(RuntimeError, match="gh pr view failed.*auth failed"):
        fetch_pr_metadata("269", runner=fake_runner)


def test_review_output_includes_stable_marker():
    from ci.ai_review import AI_REVIEW_MARKER, render_review_markdown

    rendered = render_review_markdown("gpt-test", "Looks good.")

    assert rendered.startswith(AI_REVIEW_MARKER)
    assert "### AI Code Review (gpt-test)" in rendered
    assert rendered.endswith("Looks good.")


def test_build_user_prompt_includes_metadata_and_truncates_diff(tmp_path):
    from ci.ai_review import AICodeReviewer, PRMetadata

    reviewer = AICodeReviewer(
        _write_config(tmp_path), _write_prompt(tmp_path), MagicMock()
    )
    prompt = reviewer.build_user_prompt(
        "x" * 30,
        PRMetadata(
            title="Add context",
            body="Intent body",
            milestone="Phase CI",
            comments=("- reviewer: already noted",),
        ),
    )

    assert "Title: Add context" in prompt
    assert "Intent body" in prompt
    assert "- reviewer: already noted" in prompt
    assert "[... DIFF TRUNCATED FOR LENGTH ...]" in prompt


def test_generate_returns_marked_review_and_passes_expected_params(tmp_path):
    from ci.ai_review import AI_REVIEW_MARKER, AICodeReviewer, PRMetadata

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_completion("Review text")
    reviewer = AICodeReviewer(
        _write_config(tmp_path), _write_prompt(tmp_path), mock_client
    )

    review = reviewer.generate(
        "diff --git a/file b/file",
        PRMetadata("Title", "Body", "None", ()),
    )

    assert review.startswith(AI_REVIEW_MARKER)
    assert "Review text" in review
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-5.4-mini"
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["max_completion_tokens"] == 1600


def test_generate_returns_empty_string_for_empty_diff(tmp_path):
    from ci.ai_review import AICodeReviewer, PRMetadata

    mock_client = MagicMock()
    reviewer = AICodeReviewer(
        _write_config(tmp_path), _write_prompt(tmp_path), mock_client
    )

    assert reviewer.generate("\n", PRMetadata("Title", "Body", "None", ())) == ""
    mock_client.chat.completions.create.assert_not_called()


def test_generate_raises_on_empty_openai_response(tmp_path):
    from ci.ai_review import AICodeReviewer, PRMetadata

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_completion("")
    reviewer = AICodeReviewer(
        _write_config(tmp_path), _write_prompt(tmp_path), mock_client
    )

    with pytest.raises(ValueError, match="empty response"):
        reviewer.generate("diff", PRMetadata("Title", "Body", "None", ()))


def test_missing_api_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from ci.ai_review import build_client_from_env

    with (
        patch("ci.ai_review.load_dotenv"),
        pytest.raises(ValueError, match="OPENAI_API_KEY"),
    ):
        build_client_from_env(_write_config(tmp_path))


def test_openai_client_built_with_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from ci.ai_review import build_client_from_env

    with (
        patch("ci.ai_review.load_dotenv"),
        patch("ci.ai_review.OpenAI") as mock_openai,
    ):
        build_client_from_env(_write_config(tmp_path))

    mock_openai.assert_called_once_with(api_key="test-key")


def test_ollama_provider_does_not_require_api_key(tmp_path):
    from ci.ai_review import build_client_from_env

    with (
        patch("ci.ai_review.load_dotenv"),
        patch("ci.ai_review.OpenAI") as mock_openai,
    ):
        build_client_from_env(_write_config(tmp_path, MINIMAL_CONFIG_OLLAMA))

    mock_openai.assert_called_once_with(
        base_url="http://localhost:11434/v1", api_key="ollama"
    )
