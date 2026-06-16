#!/usr/bin/env python3
"""Post an LLM code review of a PR diff with rich context — stdlib only.

Reads a unified diff on stdin (piped from ``gh pr diff --function-context``),
fetches PR metadata and file paths via the ``gh`` CLI, sends the bundled
context to the OpenAI Chat Completions API, and prints markdown to stdout.

Env:
  OPENAI_API_KEY   required — the review key
  OPENAI_MODEL     model id (default: gpt-4o-mini)
  REVIEW_PROMPT    system prompt override
  MAX_DIFF_CHARS   truncate the diff payload above this (default: 150000)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

DEFAULT_SYSTEM_PROMPT = """You are an elite, pragmatic senior systems and DevOps engineer performing a PR code review.
You are given the PR metadata (intent) and the code changes.

CRITICAL RULES:
1. Focus heavily on logical bugs, edge cases, performance regressions, resource leaks, or security flaws.
2. Cross-reference the "Existing Discussion". Do not repeat issues or nitpicks that humans have already pointed out.
3. Evaluate the diff against the PR Description. Does the code actually safely achieve the stated intent?
4. Do not complain about missing context or imports unless you are certain they are broken.
5. Be concise and technical. If the code looks great, state that clearly and briefly.
"""


def get_pr_metadata() -> dict:
    """Fetches high-level PR details using the preinstalled gh CLI."""
    try:
        res = subprocess.run(
            ["gh", "pr", "view", "--json", "title,body,milestone,comments"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(res.stdout)
    except Exception as e:
        print(f"Warning: Failed to fetch PR metadata via gh CLI: {e}", file=sys.stderr)
        return {}


def main() -> int:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        return 1

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    system_prompt = os.environ.get("REVIEW_PROMPT", DEFAULT_SYSTEM_PROMPT).strip()
    max_chars = int(os.environ.get("MAX_DIFF_CHARS", "150000"))

    # Read the incoming diff from stdin
    diff = sys.stdin.read()
    if not diff.strip():
        print("Empty diff, nothing to review.", file=sys.stderr)
        return 0

    # 1. Gather rich context using local gh CLI
    metadata = get_pr_metadata()
    title = metadata.get("title", "Unknown Title")
    body = metadata.get("body", "No description provided.")
    milestone = (
        metadata.get("milestone", {}).get("title", "None")
        if metadata.get("milestone")
        else "None"
    )

    comments = metadata.get("comments", [])
    comments_summary = [
        f"- {c['author']['login']}: {c['body'].strip()}" for c in comments
    ]
    comments_block = (
        "\n".join(comments_summary) if comments_summary else "No comments yet."
    )

    # 2. Guard payload sizes
    truncated = len(diff) > max_chars
    if truncated:
        diff = diff[:max_chars] + "\n\n[... DIFF TRUNCATED FOR LENGTH ...]"

    # 3. Construct structured LLM prompt
    user_content = (
        f"=== PULL_REQUEST CONTEXT ===\n"
        f"Title: {title}\n"
        f"Milestone: {milestone}\n"
        f"Description/Intent:\n{body}\n\n"
        f"Existing Discussion:\n{comments_block}\n"
        f"============================\n\n"
        f"Please review the following unified diff based on the context above:\n\n"
        f"```diff\n{diff}\n```"
    )

    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }
    ).encode()

    req = urllib.request.Request(
        OPENAI_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            response_body = json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        print(f"OpenAI API error {exc.code}: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"OpenAI request failed: {exc.reason}", file=sys.stderr)
        return 1

    try:
        review = response_body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        print(f"Unexpected OpenAI response shape: {response_body}", file=sys.stderr)
        return 1

    # Print stable tracking block for easy updating/overwriting by the workflow
    print(f"\n### AI Code Review ({model})\n\n{review}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
