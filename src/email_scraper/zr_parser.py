import quopri
import re
from urllib.parse import urlparse
from datetime import datetime, timezone
from job_scraper.models import JobPosting
from email_scraper.zr_scraper import fetch_job_details_from_url


def parse_zr_plaintext(raw_payload: str | bytes) -> list[JobPosting]:
    # 1. Decode the quoted-printable string back into standard UTF-8 text
    if isinstance(raw_payload, str):
        raw_payload = raw_payload.encode("utf-8")

    decoded_text = quopri.decodestring(raw_payload).decode("utf-8")
    postings = []

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

        title = title_url_match.group(1).strip()
        # Clean up any leftover intro text like "Hi Magnus, Here are today's jobs..."
        if "recommended for you:" in title:
            title = title.split("recommended for you:")[-1].strip()

        url = title_url_match.group(2).strip()

        # 4. Extract the obfuscated ID from the /km/ path
        parsed_url = urlparse(url)
        job_id = (
            parsed_url.path.split("/")[-1] if "/km/" in parsed_url.path else "unknown"
        )

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

        # 6. Use our scraper tool to fetch the full description and posted_at date from the URL if needed
        description, posted_at = fetch_job_details_from_url(url)

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
        )
        posting.compute_hash()
        postings.append(posting)

    return postings
