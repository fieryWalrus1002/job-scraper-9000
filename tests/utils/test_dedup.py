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
    assert [j["source_job_id"] for j in deduped] == ["1", "3"]


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
