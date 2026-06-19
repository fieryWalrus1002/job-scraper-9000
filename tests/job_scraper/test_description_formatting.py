from job_scraper.description_formatting import html_to_markdown
from job_scraper.pii import scrub


def test_html_to_markdown_empty_input():
    assert html_to_markdown("") == ""
    assert html_to_markdown(None) == ""


def test_html_to_markdown_preserves_bullets_and_emphasis():
    html = """
    <div>
      <p><strong>Key Responsibilities</strong></p>
      <ul>
        <li>Build Python services</li>
        <li>Own production systems</li>
      </ul>
    </div>
    """

    markdown = html_to_markdown(html)

    assert "**Key Responsibilities**" in markdown
    assert "- Build Python services" in markdown
    assert "- Own production systems" in markdown
    assert "<li>" not in markdown


def test_html_to_markdown_keeps_phone_punctuation_for_pii_scrubber():
    markdown = html_to_markdown("<p>Contact hiring@example.com or 555-867-5309.</p>")

    scrubbed, counts = scrub(markdown)

    assert scrubbed == "Contact [EMAIL_REDACTED] or [PHONE_REDACTED]."
    assert counts == {"email": 1, "phone": 1}
