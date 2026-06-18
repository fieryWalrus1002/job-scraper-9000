"""Tests for email_scraper.zr_parser — the core ZR email → JobPosting parser.

Covers: QP decode, regex chunking, field extraction (title, company, location,
salary), edge cases (missing fields, noise text, bytes input), and JobPosting
construction (source, hash, timestamps).
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from email_scraper.zr_parser import parse_zr_plaintext


# ---------------------------------------------------------------------------
# Fixtures — synthetic payloads for targeted tests
# ---------------------------------------------------------------------------


@pytest.fixture
def single_job_payload():
    """Minimal QP-encoded payload with one complete job block."""
    return (
        " Back End Developer  <https://www.ziprecruiter.com/km/abc123>\r\n"
        "\r\n"
        "Maximus • Austin, TX\r\n"
        "\r\n"
        "$100K - $145K / yr\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/km/abc123>"
    )


@pytest.fixture
def multi_job_payload():
    """QP-encoded payload with three distinct job blocks."""
    return (
        " Job A  <https://www.ziprecruiter.com/km/idA>\r\n"
        "\r\n"
        "CompanyA • New York, NY • Remote\r\n"
        "\r\n"
        "$120K - $160K / yr\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/km/idA>\r\n"
        " Job B  <https://www.ziprecruiter.com/km/idB>\r\n"
        "\r\n"
        "CompanyB • Chicago, IL\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/km/idB>\r\n"
        " Job C  <https://www.ziprecruiter.com/km/idC>\r\n"
        "\r\n"
        "CompanyC\r\n"
        "\r\n"
        "$50 - $75 / hr\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/km/idC>"
    )


@pytest.fixture
def no_salary_payload():
    """Payload with a job that has no salary line."""
    return (
        " Software Engineer  <https://www.ziprecruiter.com/km/noSalary>\r\n"
        "\r\n"
        "SomeCorp • Denver, CO\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/km/noSalary>"
    )


@pytest.fixture
def minimal_payload():
    """Payload with only title+URL and View Details — no company/location/salary."""
    return (
        " Bare Minimum Job  <https://www.ziprecruiter.com/km/minimal>\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/km/minimal>"
    )


@pytest.fixture
def salary_monthly_payload():
    """Payload with monthly salary."""
    return (
        " Staff Engineer  <https://www.ziprecruiter.com/km/monthly>\r\n"
        "\r\n"
        "MonyCorp • Remote\r\n"
        "\r\n"
        "$8K - $12K / mo\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/km/monthly>"
    )


@pytest.fixture
def salary_no_k_payload():
    """Payload with salary without K suffix."""
    return (
        " Engineer  <https://www.ziprecruiter.com/km/noK>\r\n"
        "\r\n"
        "PlainCorp\r\n"
        "\r\n"
        "$100000 - $150000 / yr\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/km/noK>"
    )


@pytest.fixture
def greeting_merged_payload():
    """Payload where the first job title is on the same line as the greeting."""
    return (
        "Hi Magnus,\r\n"
        " Here are today's jobs recommended for you:\r\n"
        " DevOps Engineer  <https://www.ziprecruiter.com/km/greet1>\r\n"
        "\r\n"
        "GreetCorp • Seattle, WA\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/km/greet1>"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(payload, fetch_returns=("Full description", "2024-01-15T00:00:00Z")):
    """Parse *payload* with mocked enrich_job_url and datetime.

    ``fetch_returns`` stays a (description, posted_at) pair for call-site
    brevity; we derive the enrichment status the router would report so the
    parser sees the real 3-tuple shape.
    """
    description, posted_at = fetch_returns
    status = "enriched" if (description or posted_at) else "unenriched"
    fixed_dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    with (
        patch(
            "email_scraper.zr_parser.enrich_job_url",
            return_value=(description, posted_at, status, None),
        ),
        patch("email_scraper.zr_parser.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = fixed_dt
        mock_dt.timezone = timezone
        return parse_zr_plaintext(payload)


# ---------------------------------------------------------------------------
# Tests — QP decoding & input handling
# ---------------------------------------------------------------------------


def test_handles_bytes_input():
    """Parser accepts bytes input (QP-encoded bytes)."""
    payload = " Test Job  <https://www.ziprecruiter.com/km/bytesTest>\r\n\r\n View Details  <https://www.ziprecruiter.com/km/bytesTest>"
    result = _parse(payload.encode("utf-8"))
    assert len(result) == 1
    assert result[0].title == "Test Job"


def test_handles_string_input():
    """Parser accepts str input (QP-encoded string)."""
    payload = " Test Job  <https://www.ziprecruiter.com/km/strTest>\r\n\r\n View Details  <https://www.ziprecruiter.com/km/strTest>"
    result = _parse(payload)
    assert len(result) == 1
    assert result[0].title == "Test Job"


def test_empty_payload_returns_empty_list():
    assert parse_zr_plaintext("") == []
    assert parse_zr_plaintext(b"") == []


def test_qp_decoding_roundtrip():
    """Quoted-printable encoded chars (like =E2=80=A2 for •) decode correctly.

    The • is the company/location delimiter — after QP decode + split,
    company and location should be properly separated.
    """
    # =E2=80=A2 is the QP encoding of UTF-8 bullet (•)
    payload = (
        " Job  <https://www.ziprecruiter.com/km/qp>\r\n"
        "\r\n"
        "CorpA =E2=80=A2 Location\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/km/qp>"
    )
    result = _parse(payload)
    assert len(result) == 1
    # QP-decoded • serves as the split delimiter → company/location separated
    assert result[0].company == "CorpA"
    assert result[0].location == "Location"


# ---------------------------------------------------------------------------
# Tests — job block splitting
# ---------------------------------------------------------------------------


def test_parses_single_job(single_job_payload):
    jobs = _parse(single_job_payload)
    assert len(jobs) == 1


def test_parses_multiple_jobs(multi_job_payload):
    jobs = _parse(multi_job_payload)
    assert len(jobs) == 3


def test_splitting_by_view_details():
    """Each 'View Details <url>' marks the end of a job block."""
    payload = (
        " Job1  <https://www.ziprecruiter.com/km/1>\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/km/1>\r\n"
        " Job2  <https://www.ziprecruiter.com/km/2>\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/km/2>"
    )
    jobs = _parse(payload)
    assert len(jobs) == 2
    assert jobs[0].title == "Job1"
    assert jobs[1].title == "Job2"


# ---------------------------------------------------------------------------
# Tests — field extraction
# ---------------------------------------------------------------------------


def test_extracts_title(single_job_payload):
    jobs = _parse(single_job_payload)
    assert jobs[0].title == "Back End Developer"


def test_extracts_url(single_job_payload):
    jobs = _parse(single_job_payload)
    assert jobs[0].source_url == "https://www.ziprecruiter.com/km/abc123"


def test_extracts_company(single_job_payload):
    jobs = _parse(single_job_payload)
    assert jobs[0].company == "Maximus"


def test_extracts_location(single_job_payload):
    jobs = _parse(single_job_payload)
    assert jobs[0].location == "Austin, TX"


def test_extracts_location_with_remote(multi_job_payload):
    """Location with '• Remote' keeps the full chain."""
    jobs = _parse(multi_job_payload)
    # Job A: "CompanyA • New York, NY • Remote"
    assert jobs[0].location == "New York, NY • Remote"


def test_company_only_no_location(multi_job_payload):
    """Job C has only 'CompanyC' with no location."""
    jobs = _parse(multi_job_payload)
    assert jobs[2].company == "CompanyC"
    assert jobs[2].location == "Unknown"


def test_missing_company_defaults_to_unknown(minimal_payload):
    jobs = _parse(minimal_payload)
    assert jobs[0].company == "Unknown"


def test_missing_location_defaults_to_unknown(minimal_payload):
    jobs = _parse(minimal_payload)
    assert jobs[0].location == "Unknown"


# ---------------------------------------------------------------------------
# Tests — salary extraction
# ---------------------------------------------------------------------------


def test_extracts_salary_yearly(single_job_payload):
    jobs = _parse(single_job_payload)
    assert jobs[0].salary_min_usd == 100_000
    assert jobs[0].salary_max_usd == 145_000
    assert jobs[0].salary_period == "yearly"


def test_extracts_salary_hourly(multi_job_payload):
    """Job C: $50 - $75 / hr."""
    jobs = _parse(multi_job_payload)
    assert jobs[2].salary_min_usd == 50
    assert jobs[2].salary_max_usd == 75
    assert jobs[2].salary_period == "hourly"


def test_extracts_salary_monthly(salary_monthly_payload):
    jobs = _parse(salary_monthly_payload)
    assert jobs[0].salary_min_usd == 8_000
    assert jobs[0].salary_max_usd == 12_000
    assert jobs[0].salary_period == "monthly"


def test_extracts_salary_without_k_suffix(salary_no_k_payload):
    """$100000 - $150000 / yr (no K)."""
    jobs = _parse(salary_no_k_payload)
    assert jobs[0].salary_min_usd == 100_000
    assert jobs[0].salary_max_usd == 150_000
    assert jobs[0].salary_period == "yearly"


def test_missing_salary_defaults_to_none(no_salary_payload):
    jobs = _parse(no_salary_payload)
    assert jobs[0].salary_min_usd is None
    assert jobs[0].salary_max_usd is None
    assert jobs[0].salary_period is None


# ---------------------------------------------------------------------------
# Tests — job ID extraction
# ---------------------------------------------------------------------------


def test_extracts_job_id_from_km_path(single_job_payload):
    jobs = _parse(single_job_payload)
    assert jobs[0].source_job_id == "abc123"


def test_listing_key_overrides_job_id_and_stabilizes_hash():
    """Same listing via two rotating tokens → same dedup_hash (the whole point)."""
    fixed_dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def _parse_url(km_id):
        payload = (
            f" Back End Developer  <https://www.ziprecruiter.com/km/{km_id}>\r\n\r\n"
            "Maximus • Austin, TX\r\n\r\n"
            f" View Details  <https://www.ziprecruiter.com/km/{km_id}>"
        )
        with (
            patch(
                "email_scraper.zr_parser.enrich_job_url",
                return_value=("desc", "2024-01-01", "enriched", "LISTING-STABLE"),
            ),
            patch("email_scraper.zr_parser.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fixed_dt
            mock_dt.timezone = timezone
            return parse_zr_plaintext(payload)[0]

    a = _parse_url("AAArotating-token-one")
    b = _parse_url("AAEdifferent-token-two")
    assert a.source_job_id == b.source_job_id == "LISTING-STABLE"
    assert a.dedup_hash == b.dedup_hash


def test_extracts_job_id_from_ekm_path():
    """External-handoff (/ekm/) links also carry the id as the last segment."""
    payload = (
        " Ext Job  <https://www.ziprecruiter.com/ekm/extId123>\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/ekm/extId123>"
    )
    jobs = _parse(payload)
    assert jobs[0].source_job_id == "extId123"


def test_job_id_fallback_to_unknown():
    """URL without /km/ path falls back to 'unknown'."""
    payload = (
        " Job  <https://www.ziprecruiter.com/jobs/some-other-path>\r\n"
        "\r\n"
        " View Details  <https://www.ziprecruiter.com/jobs/some-other-path>"
    )
    jobs = _parse(payload)
    assert jobs[0].source_job_id == "unknown"


# ---------------------------------------------------------------------------
# Tests — JobPosting construction
# ---------------------------------------------------------------------------


def test_sets_source_to_ziprecruiter_email(single_job_payload):
    jobs = _parse(single_job_payload)
    assert jobs[0].source == "ZipRecruiter_Email"


def test_computes_dedup_hash(single_job_payload):
    jobs = _parse(single_job_payload)
    assert jobs[0].dedup_hash != ""
    assert len(jobs[0].dedup_hash) == 64  # SHA-256 hex


def test_sets_scraped_at_timestamp(single_job_payload):
    jobs = _parse(single_job_payload)
    assert "2024-01-15" in jobs[0].scraped_at


def test_calls_enrich_for_each_job(multi_job_payload):
    """enrich_job_url is called once per job block."""
    with (
        patch("email_scraper.zr_parser.enrich_job_url") as mock_enrich,
        patch("email_scraper.zr_parser.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_dt.timezone = timezone
        mock_enrich.return_value = ("desc", "2024-01-01", "enriched", None)
        parse_zr_plaintext(multi_job_payload)
        assert mock_enrich.call_count == 3


def test_description_and_posted_at_from_fetch(single_job_payload):
    jobs = _parse(single_job_payload, fetch_returns=("Custom desc", "2024-06-01"))
    assert jobs[0].description == "Custom desc"
    assert jobs[0].posted_at == "2024-06-01"


def test_fetch_returns_none_gracefully(single_job_payload):
    """When enrichment yields nothing, posting still created."""
    jobs = _parse(single_job_payload, fetch_returns=(None, None))
    assert len(jobs) == 1
    assert jobs[0].description is None
    assert jobs[0].posted_at is None


def test_records_enrichment_status(single_job_payload):
    """The router's status is recorded on the posting."""
    jobs = _parse(single_job_payload, fetch_returns=("desc", "2024-06-01"))
    assert jobs[0].enrichment_status == "enriched"

    jobs = _parse(single_job_payload, fetch_returns=(None, None))
    assert jobs[0].enrichment_status == "unenriched"


def test_enrichment_status_none_when_not_scraping(single_job_payload):
    """With scrape_details off, enrichment is never attempted (status None)."""
    jobs = parse_zr_plaintext(single_job_payload, scrape_details=False)
    assert jobs[0].enrichment_status is None


# ---------------------------------------------------------------------------
# Tests — greeting / noise handling
# ---------------------------------------------------------------------------


def test_strips_intro_text_from_title(greeting_merged_payload):
    """When title line contains 'recommended for you:', strip the prefix."""
    jobs = _parse(greeting_merged_payload)
    # The first block contains the greeting merged with the first job title.
    # After stripping, title should be clean.
    assert len(jobs) == 1
    assert "recommended for you" not in jobs[0].title
    assert jobs[0].title == "DevOps Engineer"


# ---------------------------------------------------------------------------
# Tests — real email fixture
# ---------------------------------------------------------------------------


def test_parses_real_email_fixture(zr_email_qp_payload):
    """End-to-end: parse the real ZR email fixture."""
    jobs = _parse(zr_email_qp_payload)
    # The real email has ~25 job listings.
    assert len(jobs) >= 10, (
        f"Expected at least 10 jobs from real email, got {len(jobs)}"
    )


def test_real_email_has_valid_sources(zr_email_qp_payload):
    jobs = _parse(zr_email_qp_payload)
    assert all(j.source == "ZipRecruiter_Email" for j in jobs)


def test_real_email_has_dedup_hashes(zr_email_qp_payload):
    jobs = _parse(zr_email_qp_payload)
    assert all(j.dedup_hash and len(j.dedup_hash) == 64 for j in jobs)


def test_real_email_platform_lifecycle_engineer(zr_email_qp_payload):
    """Verify the namesake job from the email subject is parsed correctly."""
    jobs = _parse(zr_email_qp_payload)
    platform_jobs = [j for j in jobs if "Platform Lifecycle Engineer" in j.title]
    assert len(platform_jobs) >= 1
    job = platform_jobs[0]
    assert job.company == "DataAnnotation"
    assert "Saint Petersburg" in job.location
    assert job.salary_min_usd == 50
    assert job.salary_max_usd == 100
    assert job.salary_period == "hourly"


def test_real_email_has_unique_dedup_hashes(zr_email_qp_payload):
    """Each parsed job should have a unique dedup_hash."""
    jobs = _parse(zr_email_qp_payload)
    hashes = [j.dedup_hash for j in jobs]
    assert len(hashes) == len(set(hashes)), "Duplicate dedup hashes found"
