#!/usr/bin/env python3
"""Post an LLM code review of a PR diff — stdlib only, no third-party code.

Reads a unified diff on stdin (piped from ``gh pr diff``), sends it to the
OpenAI Chat Completions API, and prints the review markdown to stdout (the
workflow pipes that to ``gh pr comment``). The point: the OpenAI key and the
GitHub token only ever touch code in *this* repo plus the runner's
preinstalled ``gh`` CLI — no third-party Action runs with our secrets.

The diff still goes to OpenAI (inherent to any AI review); this only removes
the third-party-code trust surface, not the data egress.

Env:
  OPENAI_API_KEY   required — the review key
  OPENAI_MODEL     model id (default: gpt-4o-mini)
  REVIEW_PROMPT    system prompt (default: a terse fallback)
  MAX_DIFF_CHARS   truncate the diff above this many chars (default: 200000)

Endpoint/response shape follow the Chat Completions API; if the chosen model
only supports the Responses API, adjust OPENAI_URL and the parse below.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def main() -> int:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        return 1

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    system_prompt = os.environ.get("REVIEW_PROMPT", "Review this diff concisely.")
    max_chars = int(os.environ.get("MAX_DIFF_CHARS", "200000"))

    diff = sys.stdin.read()
    if not diff.strip():
        print("_AI review: empty diff, nothing to review._")
        return 0

    truncated = len(diff) > max_chars
    if truncated:
        diff = diff[:max_chars]

    user_content = (
        "Review the following unified diff.\n\n"
        + ("(diff truncated for length)\n\n" if truncated else "")
        + f"```diff\n{diff}\n```"
    )

    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
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
            body = json.load(resp)
    except urllib.error.HTTPError as exc:
        # Fail loud: surface status + body so a bad model id or auth error is
        # obvious in the Actions log instead of silently producing nothing.
        detail = exc.read().decode(errors="replace")
        print(f"OpenAI API error {exc.code}: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"OpenAI request failed: {exc.reason}", file=sys.stderr)
        return 1

    try:
        review = body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        print(f"Unexpected OpenAI response shape: {body}", file=sys.stderr)
        return 1

    # Stable marker line so a later version can find-and-update one comment
    # instead of posting a fresh one per push.
    print(f"<!-- ai-code-review -->\n### AI code review ({model})\n\n{review}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
