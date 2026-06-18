"""Tests for email_scraper.enrich_cli — the DB-free enrichment frontend's writer."""

import json

from email_scraper.enrich_cli import write_enriched
from job_scraper.models import JobPosting


def _job(title="Civil Engineer") -> JobPosting:
    job = JobPosting(
        source="ZipRecruiter_Email",
        source_job_id="LISTING-1",
        source_url="https://www.ziprecruiter.com/km/x",
        title=title,
        company="Acme",
        location="Remote",
        posted_at="2026-06-17T00:00:00Z",
        description="desc",
        scraped_at="2026-06-18T00:00:00Z",
        enrichment_status="enriched",
    )
    job.compute_hash()
    return job


def test_write_enriched_is_asdict_jsonl(tmp_path):
    out = write_enriched([_job("A"), _job("B")], tmp_path / "enriched.jsonl")
    lines = out.read_text().strip().split("\n")
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["title"] == "A"
    assert rec["enrichment_status"] == "enriched"
    assert rec["dedup_hash"]


def test_round_trips_to_jobposting(tmp_path):
    out = write_enriched([_job("A")], tmp_path / "e.jsonl")
    rec = json.loads(out.read_text().strip())
    # The score half reconstructs JobPosting(**rec) — must not raise.
    assert JobPosting(**rec).title == "A"
