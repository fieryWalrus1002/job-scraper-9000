from utils.dedup import dedup_jobs


def _job(**overrides) -> dict:
    base = {
        "source": "test",
        "source_job_id": "1",
        "title": "Engineer",
        "company": "Acme",
        "location": "Remote",
        "description": "This is a remote job.",
        "dedup_hash": "hashA",
    }
    return {**base, **overrides}


def test_dedup_jobs_drops_duplicate_dedup_hash():
    jobs = [
        _job(source_job_id="1", dedup_hash="hashA"),
        _job(source_job_id="2", dedup_hash="hashA"),
        _job(source_job_id="3", dedup_hash="hashB"),
    ]
    deduped, dropped = dedup_jobs(jobs)
    assert dropped == 1
    # Tie on description length → first-seen wins.
    assert [j["source_job_id"] for j in deduped] == ["1", "3"]


def test_dedup_jobs_prefers_longest_description_within_group():
    # Interleave: stub (empty desc) first, full record second, stub again third.
    # Survivor must be the full record — losing it would silently drop the only
    # analyzable copy of this job.
    full = "Full posting text describing the role in detail."
    jobs = [
        _job(source_job_id="1", dedup_hash="hashA", description=""),
        _job(source_job_id="2", dedup_hash="hashA", description=full),
        _job(source_job_id="3", dedup_hash="hashA", description="short"),
    ]
    deduped, dropped = dedup_jobs(jobs)
    assert dropped == 2
    assert len(deduped) == 1
    assert deduped[0]["source_job_id"] == "2"
    assert deduped[0]["description"] == full


def test_dedup_jobs_preserves_first_seen_position_of_winning_group():
    jobs = [
        _job(source_job_id="A", dedup_hash="hashA", description=""),
        _job(source_job_id="B", dedup_hash="hashB", description="solo"),
        _job(source_job_id="C", dedup_hash="hashA", description="winner"),
    ]
    deduped, _ = dedup_jobs(jobs)
    # Group hashA's slot is index 0 (first occurrence), even though C wins it.
    assert [j["source_job_id"] for j in deduped] == ["C", "B"]


def test_dedup_jobs_falls_back_to_source_job_id_when_no_dedup_hash():
    jobs = [
        _job(source_job_id="X", dedup_hash=""),
        _job(source_job_id="X", dedup_hash=""),
        _job(source_job_id="Y", dedup_hash=""),
    ]
    deduped, dropped = dedup_jobs(jobs)
    assert dropped == 1
    assert [j["source_job_id"] for j in deduped] == ["X", "Y"]


def test_dedup_jobs_passes_through_jobs_missing_both_keys():
    jobs = [_job(source_job_id="", dedup_hash=""), _job(source_job_id="", dedup_hash="")]
    deduped, dropped = dedup_jobs(jobs)
    assert dropped == 0
    assert len(deduped) == 2
