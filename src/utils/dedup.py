def dedup_jobs(jobs: list[dict]) -> tuple[list[dict], int]:
    """Dedup by `dedup_hash` (fallback: `source_job_id`); keep the longest-description winner.

    Returns (deduped_jobs, dropped_count). Within each dedup group the record
    with the longest `description` wins — this protects against scrapers that
    emit a stub record (empty description) earlier in the batch than a full
    record for the same job, which would otherwise be silently dropped. Tie
    on description length: first-seen wins. Output preserves the position of
    each group's first occurrence. Jobs missing both keys pass through.
    """
    best_idx: dict[str, int] = {}
    out: list[dict] = []
    for job in jobs:
        key = job.get("dedup_hash") or job.get("source_job_id")
        if not key:
            out.append(job)
            continue
        if key not in best_idx:
            best_idx[key] = len(out)
            out.append(job)
            continue
        slot = best_idx[key]
        incoming = len(job.get("description") or "")
        current = len(out[slot].get("description") or "")
        if incoming > current:
            out[slot] = job
    return out, len(jobs) - len(out)
