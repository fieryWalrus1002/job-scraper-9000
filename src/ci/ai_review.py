"""AI code-review helper used by the GitHub Actions workflow."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import yaml
from dotenv import load_dotenv
from openai import OpenAI

log = logging.getLogger(__name__)

AI_REVIEW_MARKER = "<!-- ai-code-review -->"


@dataclass(frozen=True)
class PRMetadata:
    """Small, prompt-safe representation of PR context."""

    title: str
    body: str
    milestone: str
    comments: tuple[str, ...]


class AICodeReviewer:
    """Generate an AI code review from a diff and PR metadata."""

    def __init__(
        self,
        config_path: str,
        prompt_path: str,
        client: OpenAI,
    ):
        self.config = self._load_config(config_path)
        self.system_prompt = self._load_and_strip_prompt(prompt_path)
        self.client = client

    def _load_config(self, path: str) -> dict[str, Any]:
        return yaml.safe_load(pathlib.Path(path).read_text())

    def _load_and_strip_prompt(self, path: str) -> str:
        content = pathlib.Path(path).read_text()
        if content.startswith("---"):
            parts = content.split("---")
            if len(parts) >= 3:
                content = "---".join(parts[2:])
        return content.strip()

    @property
    def llm_config(self) -> dict[str, Any]:
        return self.config["llm"]

    @property
    def max_diff_chars(self) -> int:
        return int(self.config.get("max_diff_chars", 150_000))

    def build_user_prompt(self, git_diff: str, metadata: PRMetadata) -> str:
        diff = self._truncate_diff(git_diff)
        comments_block = (
            "\n".join(metadata.comments) if metadata.comments else "No comments yet."
        )

        return (
            "=== PULL_REQUEST CONTEXT ===\n"
            f"Title: {metadata.title}\n"
            f"Milestone: {metadata.milestone}\n"
            f"Description/Intent:\n{metadata.body}\n\n"
            f"Existing Discussion:\n{comments_block}\n"
            "============================\n\n"
            "Please review the following unified diff based on the context above:\n\n"
            f"```diff\n{diff}\n```"
        )

    def generate(self, git_diff: str, metadata: PRMetadata) -> str:
        if not git_diff.strip():
            log.info("Empty diff, nothing to review.")
            return ""

        model = self.llm_config["model"]
        log.info("Generating AI code review using model: %s", model)

        try:
            response = self.client.chat.completions.create(
                model=model,
                temperature=self.llm_config.get("temperature", 0.2),
                max_tokens=self.llm_config.get("max_tokens"),
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {
                        "role": "user",
                        "content": self.build_user_prompt(git_diff, metadata),
                    },
                ],
            )
            if not response.choices or not response.choices[0].message.content:
                raise ValueError("Received empty response from OpenAI API.")
            review = response.choices[0].message.content.strip()
            log.info("Successfully generated AI code review.")
            return render_review_markdown(model, review)
        except Exception:
            log.exception("Failed to generate AI code review")
            raise

    def _truncate_diff(self, git_diff: str) -> str:
        if len(git_diff) <= self.max_diff_chars:
            return git_diff
        return (
            git_diff[: self.max_diff_chars] + "\n\n[... DIFF TRUNCATED FOR LENGTH ...]"
        )


def render_review_markdown(model: str, review: str) -> str:
    """Render final PR-comment markdown with the stable update marker."""
    return f"{AI_REVIEW_MARKER}\n### AI Code Review ({model})\n\n{review}"


def build_client_from_env(config_path: str) -> OpenAI:
    """Build an OpenAI-compatible client from non-secret YAML plus env secrets."""
    load_dotenv()
    config = yaml.safe_load(pathlib.Path(config_path).read_text())
    provider = config["llm"].get("provider", "openai").lower()

    if provider == "ollama":
        base_url = config["llm"].get("ollama_base_url", "http://localhost:11434/v1")
        return OpenAI(base_url=base_url, api_key="ollama")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is required.")
    return OpenAI(api_key=api_key)


def fetch_pr_metadata(
    pr: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> PRMetadata:
    """Fetch PR metadata via gh CLI and fail loudly if gh is unavailable/broken."""
    cmd = ["gh", "pr", "view"]
    if pr:
        cmd.append(pr)
    cmd.extend(["--json", "title,body,milestone,comments"])

    try:
        result = runner(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "<no stderr>"
        raise RuntimeError(
            f"gh pr view failed with exit code {exc.returncode}: {stderr}"
        ) from exc

    return parse_pr_metadata(json.loads(result.stdout))


def parse_pr_metadata(raw: dict[str, Any]) -> PRMetadata:
    """Parse gh's JSON shape into prompt-safe metadata."""
    milestone = raw.get("milestone") or {}
    milestone_title = milestone.get("title") if isinstance(milestone, dict) else None
    comments = raw.get("comments") or []
    return PRMetadata(
        title=raw.get("title") or "Unknown Title",
        body=raw.get("body") or "No description provided.",
        milestone=milestone_title or "None",
        comments=tuple(
            format_comment_summary(c) for c in comments if has_comment_body(c)
        ),
    )


def has_comment_body(comment: object) -> bool:
    if not isinstance(comment, dict):
        return False
    return bool(str(comment.get("body") or "").strip())


def format_comment_summary(comment: dict[str, Any]) -> str:
    """Return one prompt-safe comment summary line."""
    author = comment.get("author") or {}
    login = author.get("login") if isinstance(author, dict) else None
    body = str(comment.get("body") or "").strip()
    return f"- {login or 'unknown'}: {body}"


def build_git_diff_command(base_ref: str, head_ref: str = "HEAD") -> Sequence[str]:
    """Return the git command used by CI to build a function-context diff."""
    return ["git", "diff", "--function-context", f"{base_ref}...{head_ref}"]
