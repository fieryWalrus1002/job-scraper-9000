"""Tests for email_scraper.process_eml_directory — the age gate.

Other behavior (payload extraction, archiving) is exercised indirectly via the
parser tests; here we focus on the freshness skip introduced for the 96h window.
"""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from email_scraper.process_eml_directory import _email_sent_at, process_eml_directory
from email_scraper.seen_store import JsonlSeenStore


def _write_eml(path, sent_at: datetime, title: str) -> None:
    """Write a minimal ZR-shaped .eml with a given Date header (7bit, no QP)."""
    url = "https://www.ziprecruiter.com/km/abc"
    body = f" {title}  <{url}>\r\n\r\nAcme • Austin, TX\r\n\r\n View Details  <{url}>"
    raw = (
        "From: ZipRecruiter <jobs@ziprecruiter.com>\r\n"
        f"Date: {format_datetime(sent_at)}\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n'
        "Content-Transfer-Encoding: 7bit\r\n"
        "\r\n"
        f"{body}\r\n"
    )
    path.write_bytes(raw.encode("utf-8"))


def test_email_sent_at_parses_date_header():
    from email import message_from_string

    msg = message_from_string("Date: Mon, 16 Jun 2026 12:00:00 +0000\r\n\r\nbody")
    sent = _email_sent_at(msg)
    assert sent is not None
    assert sent.year == 2026 and sent.month == 6 and sent.day == 16


def test_email_sent_at_missing_header_returns_none():
    from email import message_from_string

    assert _email_sent_at(message_from_string("Subject: x\r\n\r\nbody")) is None


def test_age_gate_skips_stale_keeps_fresh(tmp_path):
    now = datetime.now(timezone.utc)
    _write_eml(tmp_path / "fresh.eml", now - timedelta(hours=1), "Fresh Job")
    _write_eml(tmp_path / "stale.eml", now - timedelta(hours=200), "Stale Job")

    jobs = process_eml_directory(
        directory_path=str(tmp_path),
        scrape_details=False,
        max_age_hours=96,
    )

    titles = {j.title for j in jobs}
    assert "Fresh Job" in titles
    assert "Stale Job" not in titles


def test_no_age_gate_processes_all(tmp_path):
    now = datetime.now(timezone.utc)
    _write_eml(tmp_path / "fresh.eml", now - timedelta(hours=1), "Fresh Job")
    _write_eml(tmp_path / "stale.eml", now - timedelta(hours=200), "Stale Job")

    jobs = process_eml_directory(
        directory_path=str(tmp_path),
        scrape_details=False,
        max_age_hours=None,
    )

    assert {"Fresh Job", "Stale Job"} <= {j.title for j in jobs}


def test_invalid_max_age_raises(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="max_age_hours"):
        process_eml_directory(
            directory_path=str(tmp_path), scrape_details=False, max_age_hours=0
        )


# ---------------------------------------------------------------------------
# Layer 1 — processed-email cache (seen_store)
# ---------------------------------------------------------------------------


def test_seen_store_skips_and_records(tmp_path):
    now = datetime.now(timezone.utc)
    _write_eml(tmp_path / "msg-1.eml", now - timedelta(hours=1), "Job One")
    store = JsonlSeenStore(tmp_path / "seen.jsonl")

    first = process_eml_directory(
        directory_path=str(tmp_path), scrape_details=False, seen_store=store
    )
    assert [j.title for j in first] == ["Job One"]
    assert store.has("msg-1")  # recorded after processing

    # Second run over the same dir: the email is a cache hit → skipped entirely.
    second = process_eml_directory(
        directory_path=str(tmp_path), scrape_details=False, seen_store=store
    )
    assert second == []


def test_no_seen_store_processes_every_time(tmp_path):
    now = datetime.now(timezone.utc)
    _write_eml(tmp_path / "msg-1.eml", now - timedelta(hours=1), "Job One")

    for _ in range(2):
        jobs = process_eml_directory(directory_path=str(tmp_path), scrape_details=False)
        assert [j.title for j in jobs] == ["Job One"]
