from job_scraper.models import JobPosting


def _make_job(**overrides) -> JobPosting:
    defaults = dict(
        source="linkedin",
        source_job_id="123",
        source_url="https://example.com/jobs/123",
        title="Senior Engineer",
        company="Acme Corp",
        location="Remote",
        posted_at="2024-01-01",
        description="Great role.",
        scraped_at="2024-01-02T00:00:00+00:00",
    )
    return JobPosting(**{**defaults, **overrides})


def test_compute_hash_is_deterministic():
    job = _make_job()
    job.compute_hash()
    first = job.dedup_hash
    job.compute_hash()
    assert job.dedup_hash == first


def test_compute_hash_normalizes_case():
    lower = _make_job(company="acme corp", title="senior engineer", location="remote")
    upper = _make_job(company="ACME CORP", title="SENIOR ENGINEER", location="REMOTE")
    lower.compute_hash()
    upper.compute_hash()
    assert lower.dedup_hash == upper.dedup_hash


def test_compute_hash_normalizes_whitespace():
    stripped = _make_job(
        company="Acme Corp", title="Senior Engineer", location="Remote"
    )
    padded = _make_job(
        company="  Acme Corp  ", title="  Senior Engineer  ", location="  Remote  "
    )
    stripped.compute_hash()
    padded.compute_hash()
    assert stripped.dedup_hash == padded.dedup_hash


def test_compute_hash_differs_on_different_fields():
    a = _make_job(company="Acme", title="Engineer", location="Remote")
    b = _make_job(company="Globex", title="Engineer", location="Remote")
    a.compute_hash()
    b.compute_hash()
    assert a.dedup_hash != b.dedup_hash


def test_dedup_hash_initially_empty():
    job = _make_job()
    assert job.dedup_hash == ""
