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

    def compute_hash(self) -> None:
        key = "|".join([
            (self.company or "").lower().strip(),
            (self.title or "").lower().strip(),
            (self.location or "").lower().strip(),
        ])
        self.dedup_hash = hashlib.sha256(key.encode()).hexdigest()
