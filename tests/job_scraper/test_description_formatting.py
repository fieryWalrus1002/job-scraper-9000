from job_scraper.description_formatting import clean_description, html_to_markdown
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


def test_clean_description_unescapes_html_before_markdown_and_scrubs_pii():
    raw = """
    &lt;div&gt;
      &lt;p&gt;&lt;strong&gt;Apply now&lt;/strong&gt;&lt;/p&gt;
      &lt;ul&gt;&lt;li&gt;Build tools&lt;/li&gt;&lt;/ul&gt;
      &lt;p&gt;Email hiring@example.com or call 555-867-5309.&lt;/p&gt;
    &lt;/div&gt;
    """

    description, counts = clean_description(raw)

    assert "**Apply now**" in description
    assert "- Build tools" in description
    assert "hiring@example.com" not in description
    assert "555-867-5309" not in description
    assert "[EMAIL_REDACTED]" in description
    assert "[PHONE_REDACTED]" in description
    assert "&lt;" not in description
    assert counts == {"email": 1, "phone": 1}


def test_clean_description_empty_input_returns_empty_counts():
    assert clean_description(None) == ("", {"email": 0, "phone": 0})
