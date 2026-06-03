import hashlib
from dataclasses import dataclass, field


@dataclass
class JobPosting:
    source: str
    source_job_id: str
    source_url: str
    title: str
    company: str
    location: str
    posted_at: str | None
    description: str | None
    scraped_at: str
    scrub_counts: dict = field(default_factory=dict)
    search_params: dict = field(default_factory=dict)
    dedup_hash: str = ""
    salary_min_usd: int | None = None
    salary_max_usd: int | None = None
    salary_period: str | None = None  # 'yearly' | 'hourly' | 'monthly' etc.

    def compute_hash(self) -> None:
        # source_job_id distinguishes legitimately distinct postings that share
        # (company, title, location). SEL re-posts the same title at the same
        # location for different teams/cohorts; without source_job_id in the
        # key, those collide and the downstream AnalysisCache returns a stale
        # analysis for the second posting. `source` defends against
        # source_job_id collisions across scrapers. Tradeoff: cross-source
        # dedup of the same listing (e.g. LinkedIn mirror of a Greenhouse post)
        # is no longer collapsed by this hash — rare in practice, and a
        # separate fuzzy-match step would be the right place for that.
        key = "|".join(
            [
                (self.source or "").lower().strip(),
                (self.source_job_id or "").lower().strip(),
                (self.company or "").lower().strip(),
                (self.title or "").lower().strip(),
                (self.location or "").lower().strip(),
            ]
        )
        self.dedup_hash = hashlib.sha256(key.encode()).hexdigest()
