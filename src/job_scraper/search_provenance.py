from typing import Any

_CANONICAL = ("workplace", "keywords", "job_type", "source_detail_location")
_WORKPLACE = {"remote", "hybrid", "onsite"}
_JOB_TYPE = {"fulltime", "parttime", "contract", "internship"}

# Source-specific, non-classifier provenance a scraper may legitimately attach.
_OPAQUE_ALLOWED = {
    "board_token",
    "company",
    "experience",
    "location",
    "salary_floor",
    "sites",
    "source",
    "workday_job_req_id",
}


def build_search_params(
    *,
    workplace: str | None = None,
    keywords: str | None = None,
    job_type: str | None = None,
    source_detail_location: str | None = None,
    **opaque: Any,
) -> dict[str, Any]:
    """Return validated, flat scraper provenance for ``JobPosting.search_params``.

    Scrapers must map classifier-relevant source-native fields into the canonical
    names accepted here. Unknown keyword arguments fail loudly at the scrape
    boundary instead of silently disappearing downstream.
    """
    if workplace is not None and workplace not in _WORKPLACE:
        raise ValueError(
            f"search_params.workplace={workplace!r} not in {sorted(_WORKPLACE)}"
        )
    if job_type is not None and job_type not in _JOB_TYPE:
        raise ValueError(
            f"search_params.job_type={job_type!r} not in {sorted(_JOB_TYPE)}"
        )

    unknown = set(opaque) - _OPAQUE_ALLOWED
    if unknown:
        raise ValueError(
            f"search_params got unknown key(s) {sorted(unknown)}; "
            f"map them to a canonical field ({_CANONICAL}) or add to _OPAQUE_ALLOWED"
        )

    out: dict[str, Any] = {
        "workplace": workplace,
        "keywords": keywords,
        "job_type": job_type,
        "source_detail_location": source_detail_location,
        **opaque,
    }
    return {key: value for key, value in out.items() if value is not None}
