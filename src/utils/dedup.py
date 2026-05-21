def dedup_jobs(jobs: list[dict]) -> tuple[list[dict], int]:
    """Dedup by `dedup_hash` (fallback: `source_job_id`); keep first occurrence.

    Returns (deduped_jobs, dropped_count). Jobs missing both keys pass through
    untouched so they're never silently dropped.
    """
    seen: set[str] = set()
    deduped: list[dict] = []
    for job in jobs:
        key = job.get("dedup_hash") or job.get("source_job_id")
        if not key:
            deduped.append(job)
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append(job)
    return deduped, len(jobs) - len(deduped)
