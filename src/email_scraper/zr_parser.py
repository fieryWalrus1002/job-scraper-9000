import logging
import quopri
import re
from urllib.parse import urlparse
from datetime import datetime, timezone
from job_scraper.models import JobPosting
from email_scraper.zr_scraper import enrich_job_url

log = logging.getLogger(__name__)


def parse_zr_plaintext(
    raw_payload: str | bytes,
    max_jobs: int | None = None,
    skip_jobs: int = 0,
    scrape_details: bool = True,
) -> list[JobPosting]:
    # 1. Decode the quoted-printable string back into standard UTF-8 text
    if isinstance(raw_payload, str):
        raw_payload = raw_payload.encode("utf-8")

    decoded_text = quopri.decodestring(raw_payload).decode("utf-8")
    if max_jobs is not None and max_jobs <= 0:
        raise ValueError("max_jobs must be a positive integer")
    if skip_jobs < 0:
        raise ValueError("skip_jobs must be zero or a positive integer")

    postings = []
    matched_jobs_seen = 0

    # 2. Chunk the text by job. Every job ends with a "View Details" link.
    job_blocks = re.split(r"View Details\s+<[^>]+>", decoded_text)

    for block in job_blocks:
        block = block.strip()
        if not block:
            continue

        # 3. Extract the Title and URL
        # Looks for: {Title text}  <{URL}>
        title_url_match = re.search(r"([^\n<]+)\s+<([^>]+)>", block)
        if not title_url_match:
            continue

        if matched_jobs_seen < skip_jobs:
            matched_jobs_seen += 1
            continue
        matched_jobs_seen += 1

        title = title_url_match.group(1).strip()
        # Clean up any leftover intro text like "Hi Magnus, Here are today's jobs..."
        if "recommended for you:" in title:
            title = title.split("recommended for you:")[-1].strip()

        url = title_url_match.group(2).strip()

        # 4. Extract the obfuscated ID from the tracking path. Both ZR-hosted
        # (/km/) and external-handoff (/ekm/) links carry the id as the last path
        # segment; without covering /ekm/ too, every external job collapsed to
        # the same "unknown" id and collided in dedup.
        parsed_url = urlparse(url)
        if "/km/" in parsed_url.path or "/ekm/" in parsed_url.path:
            job_id = parsed_url.path.rstrip("/").split("/")[-1] or "unknown"
        else:
            job_id = "unknown"

        # 5. Extract Company, Location, and Salary from the remaining lines
        content_after_title = block[title_url_match.end() :].strip()
        lines = [
            line.strip() for line in content_after_title.split("\n") if line.strip()
        ]

        company, location = "Unknown", "Unknown"
        salary_min, salary_max, salary_period = None, None, None

        if lines:
            # First line is usually: Company • Location [• Remote]
            parts = [p.strip() for p in lines[0].split("•")]
            company = parts[0]
            if len(parts) > 1:
                location = " • ".join(parts[1:])  # Keep 'Location • Remote' together

        if len(lines) > 1:
            # Second line might be salary: $100K - $145K / yr
            salary_match = re.search(
                r"\$(\d+)(K?)\s*-\s*\$(\d+)(K?)\s*/\s*(yr|hr|mo)",
                lines[1],
                re.IGNORECASE,
            )
            if salary_match:
                min_val, min_k, max_val, max_k, period = salary_match.groups()

                # Convert '100K' to 100000
                salary_min = int(min_val) * (1000 if min_k.upper() == "K" else 1)
                salary_max = int(max_val) * (1000 if max_k.upper() == "K" else 1)

                # Normalize period for your dataclass
                period_map = {"yr": "yearly", "hr": "hourly", "mo": "monthly"}
                salary_period = period_map.get(period.lower())

        # 6. Enrich from the detail page if needed. The router classifies the URL
        # first, so external-ATS and expired links cost no browser launch and
        # come back with an explicit status instead of a silent (None, None).
        description, posted_at, enrichment_status = None, None, None
        if scrape_details:
            log.info("Enriching ZR job %s: %s", title, url)
            description, posted_at, enrichment_status, listing_key = enrich_job_url(url)
            # The email tracking token rotates every send, so the path-id we
            # extracted in step 4 is per-send, not per-job — the same job in two
            # emails would get two dedup_hashes (→ duplicate app rows, missed
            # AnalysisCache). The resolved page's listing_key is stable, so prefer
            # it as the identity when enrichment surfaced one.
            if listing_key:
                job_id = listing_key
            if description or posted_at:
                log.info(
                    "Enriched %s [%s]: description=%s posted_at=%s listing_key=%s",
                    title,
                    enrichment_status,
                    bool(description),
                    posted_at,
                    listing_key,
                )
            else:
                log.warning(
                    "No detail fields for %s [%s]: %s", title, enrichment_status, url
                )

        # 7. Instantiate and hash
        posting = JobPosting(
            source="ZipRecruiter_Email",
            source_job_id=job_id,
            source_url=url,
            title=title,
            company=company,
            location=location,
            posted_at=posted_at,
            description=description,
            scraped_at=datetime.now(timezone.utc).isoformat(),
            salary_min_usd=salary_min,
            salary_max_usd=salary_max,
            salary_period=salary_period,
            enrichment_status=enrichment_status,
        )
        posting.compute_hash()
        postings.append(posting)

        if max_jobs is not None and len(postings) >= max_jobs:
            break

    return postings
