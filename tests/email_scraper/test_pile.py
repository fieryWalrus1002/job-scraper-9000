"""Tests for email_scraper.pile — writing enriched jobs into the raw pile."""

import json
from pathlib import Path

from email_scraper.pile import write_pile
from job_scraper.models import JobPosting


def _job(title="Back End Developer", status="enriched") -> JobPosting:
    job = JobPosting(
        source="ZipRecruiter_Email",
        source_job_id="abc123",
        source_url="https://www.ziprecruiter.com/km/abc123",
        title=title,
        company="Acme",
        location="Austin, TX",
        posted_at="2026-06-17T00:00:00Z",
        description="A real description.",
        scraped_at="2026-06-18T00:00:00Z",
        enrichment_status=status,
    )
    job.compute_hash()
    return job


def test_writes_jsonl_under_run_date(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dest = write_pile([_job()], run_date="2026-06-18")

    assert dest is not None
    # DATA_DIR is relative ("data/raw"); cwd is tmp_path so the path is relative.
    assert dest.parent == Path("data/raw/2026-06-18")
    assert dest.name.endswith("_ZipRecruiter_Email_email-alerts.jsonl")
    assert (tmp_path / dest).exists()


def test_line_is_asdict_with_enrichment_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dest = write_pile([_job()], run_date="2026-06-18")

    lines = dest.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["title"] == "Back End Developer"
    assert record["description"] == "A real description."
    assert record["enrichment_status"] == "enriched"
    assert record["dedup_hash"]  # carried through


def test_one_line_per_job(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dest = write_pile([_job("Job A"), _job("Job B")], run_date="2026-06-18")
    assert len(dest.read_text().strip().split("\n")) == 2


def test_empty_list_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dest = write_pile([], run_date="2026-06-18")
    assert dest is None
    assert not (tmp_path / "data" / "raw").exists()


def test_flat_path_without_run_date(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dest = write_pile([_job()])
    assert dest.parent == Path("data/raw")
