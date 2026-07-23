"""Helpers for normalising scraped job description markup."""

import html

from markdownify import markdownify as _markdownify

from .pii import scrub


def html_to_markdown(html: object) -> str:
    """Convert a scraped HTML description fragment to readable Markdown.

    Job boards commonly encode structure in ``<ul>/<li>``, ``<strong>``, and
    paragraph tags. BeautifulSoup's plain ``get_text()`` drops that structure,
    while raw HTML is awkward for downstream agents and UI rendering. Markdown is
    a compact middle ground: readable as text, structured enough for renderers.

    ``escape_misc=False`` intentionally keeps phone punctuation such as
    ``555-867-5309`` intact so the PII scrubber can still recognize it.
    """
    if not html:
        return ""
    return _markdownify(
        str(html),
        bullets="-",
        heading_style="ATX",
        escape_misc=False,
    ).strip()


def clean_description(raw: object) -> tuple[str, dict]:
    """Single hygiene entry point for scraped descriptions.

    Runs unescape HTML entities → convert to Markdown → redact PII.
    Order matters: unescape first so markdownify parses real tags even on
    double-encoded input; PII scrub last so phone punctuation survives
    html_to_markdown's escape_misc=False (see #389).
    """
    if not raw:
        return "", {"email": 0, "phone": 0}
    markdown = html_to_markdown(html.unescape(str(raw)))
    return scrub(markdown)
