"""Tests for email_scraper.orchestrator — pull → enrich → pile wiring."""

from unittest.mock import patch

import pytest

from email_scraper import orchestrator
from email_scraper.zr_scraper import _HEADLESS_ENV, _PROFILE_DIR_ENV
from job_scraper.models import JobPosting


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """run() mutates the profile env vars; isolate each test from the others."""
    monkeypatch.delenv(_PROFILE_DIR_ENV, raising=False)
    monkeypatch.delenv(_HEADLESS_ENV, raising=False)


def _job(status: str, title="J") -> JobPosting:
    return JobPosting(
        source="ZipRecruiter_Email",
        source_job_id="x",
        source_url="https://www.ziprecruiter.com/km/x",
        title=title,
        company="Acme",
        location="Remote",
        posted_at=None,
        description="d" if status == "enriched" else None,
        scraped_at="2026-06-18T00:00:00Z",
        enrichment_status=status,
    )


_MIXED = [
    _job("enriched", "A"),
    _job("enriched", "B"),
    _job("external_ats", "C"),
    _job("expired", "D"),
    _job("unenriched", "E"),
]


def test_enrich_email_jobs_returns_enriched_only_no_pile():
    """The shared core filters to enriched and never writes the pile."""
    with (
        patch.object(orchestrator, "process_eml_directory", return_value=_MIXED),
        patch.object(orchestrator, "write_pile") as mock_pile,
    ):
        enriched = orchestrator.enrich_email_jobs(
            pull=False, headless=True, use_cache=False
        )

    assert [j.title for j in enriched] == ["A", "B"]
    mock_pile.assert_not_called()


def test_writes_only_enriched_jobs():
    with (
        patch.object(orchestrator, "process_eml_directory", return_value=_MIXED),
        patch.object(orchestrator, "write_pile", return_value=None) as mock_pile,
    ):
        enriched = orchestrator.run(pull=False, headless=True, use_cache=False)

    assert [j.title for j in enriched] == ["A", "B"]
    written = mock_pile.call_args.args[0]
    assert all(j.enrichment_status == "enriched" for j in written)
    assert len(written) == 2


def test_no_pull_skips_grabber():
    with (
        patch.object(orchestrator, "process_eml_directory", return_value=[]),
        patch.object(orchestrator, "write_pile", return_value=None),
        patch(
            "email_scraper.gmail_eml_grabber.download_labeled_emails_as_eml"
        ) as mock_dl,
    ):
        orchestrator.run(pull=False, headless=True, use_cache=False)

    mock_dl.assert_not_called()


def test_pull_invokes_grabber():
    with (
        patch.object(orchestrator, "process_eml_directory", return_value=[]),
        patch.object(orchestrator, "write_pile", return_value=None),
        patch(
            "email_scraper.gmail_eml_grabber.download_labeled_emails_as_eml"
        ) as mock_dl,
    ):
        orchestrator.run(pull=True, headless=True, max_emails=3, use_cache=False)

    mock_dl.assert_called_once()


def test_aborts_when_chrome_running():
    with (
        patch.object(orchestrator, "_chrome_is_running", return_value=True),
        patch.object(orchestrator, "process_eml_directory", return_value=[]),
    ):
        with pytest.raises(RuntimeError, match="Chrome is running"):
            orchestrator.run(pull=False, headless=False)


def test_profile_env_set_when_headful(monkeypatch):
    with (
        patch.object(orchestrator, "_chrome_is_running", return_value=False),
        patch.object(orchestrator, "process_eml_directory", return_value=[]),
        patch.object(orchestrator, "write_pile", return_value=None),
    ):
        orchestrator.run(
            pull=False, headless=False, profile_dir="~/.config/google-chrome"
        )

    import os

    assert os.environ[_PROFILE_DIR_ENV] == os.path.expanduser("~/.config/google-chrome")
    assert os.environ[_HEADLESS_ENV] == "0"
