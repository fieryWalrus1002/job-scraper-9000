from job_scraper.pii import scrub


def test_clean_text_unchanged():
    text, counts = scrub("No personal info here.")
    assert text == "No personal info here."
    assert counts == {"email": 0, "phone": 0}


def test_empty_string():
    text, counts = scrub("")
    assert text == ""
    assert counts == {"email": 0, "phone": 0}


def test_email_redacted():
    text, counts = scrub("Contact us at hiring@example.com for details.")
    assert "hiring@example.com" not in text
    assert "[EMAIL_REDACTED]" in text
    assert counts["email"] == 1


def test_multiple_emails_redacted():
    text, counts = scrub("Email a@b.com or c@d.org to apply.")
    assert counts["email"] == 2
    assert text.count("[EMAIL_REDACTED]") == 2


def test_phone_redacted():
    text, counts = scrub("Call us at 555-867-5309.")
    assert "555-867-5309" not in text
    assert "[PHONE_REDACTED]" in text
    assert counts["phone"] == 1


def test_phone_formats_redacted():
    cases = [
        "(800) 555-1234",
        "800.555.1234",
        "+1 800 555 1234",
    ]
    for phone in cases:
        text, counts = scrub(f"Reach us at {phone}.")
        assert counts["phone"] == 1, f"Expected phone redacted for: {phone!r}"


def test_email_and_phone_together():
    raw = "Email jobs@acme.com or call 212-555-9999."
    text, counts = scrub(raw)
    assert counts["email"] == 1
    assert counts["phone"] == 1
    assert "jobs@acme.com" not in text
    assert "212-555-9999" not in text


def test_excessive_newlines_collapsed():
    raw = "Section A\n\n\n\nSection B\n\n\n\n\nSection C"
    text, _ = scrub(raw)
    assert text == "Section A\n\nSection B\n\nSection C"


def test_newlines_with_whitespace_collapsed():
    raw = "Section A\n   \n  \nSection B"
    text, _ = scrub(raw)
    assert text == "Section A\n\nSection B"


def test_leading_trailing_whitespace_stripped():
    raw = "\n\nContent here\n\n"
    text, _ = scrub(raw)
    assert text == "Content here"
