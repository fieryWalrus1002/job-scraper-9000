# Scrape Quality Regression Detection

**Status:** Planned — not yet implemented.

______________________________________________________________________

## Problem

Scrapers break silently. When Workday changes a facet GUID, an API response key, or
pagination behaviour, the scraper still runs to completion and writes a JSONL file — it just
writes 0 jobs, or jobs with empty descriptions, or jobs with stale relative dates. There is
currently no automated check that catches this before the bad data flows downstream into the
remote-filter and semantic-similarity pipelines.

We already hit all three failure modes during the initial SEL bring-up:

- Wrong HTTP method → 0 jobs ingested
- Wrong JSON key path (`jobDescription` vs `jobPostingInfo.jobDescription`) → all descriptions empty
- `total=0` pagination quirk mishandled → 40 of 94 jobs fetched, no error raised
- `postedOn` returned as relative string → `"Posted Yesterday"` written verbatim as a date

______________________________________________________________________

## What "good data" looks like for SEL

Observed from the 2026-05-14 production scrape (94 jobs, Pullman WA filter):

| Field                         | Expected                                                    |
| ----------------------------- | ----------------------------------------------------------- |
| Job count                     | ≥ 50 (SEL Pullman typically 80–100 full-time regular roles) |
| `description` non-empty       | 100%                                                        |
| `description` length          | ≥ 500 chars (real postings are 2,300–6,300)                 |
| `posted_at` format            | ISO `YYYY-MM-DD`, not a relative string                     |
| `location`                    | No `"N Locations"` values                                   |
| Salary mention in description | ≥ 80% (SEL publishes pay ranges consistently)               |

These thresholds should be tuned per-scraper as we add more sources.

______________________________________________________________________

## Proposed two-layer approach

### Layer 1 — Post-scrape quality gate (catches live API drift)

A lightweight validator that runs automatically at the end of every `run-config` or CLI scrape
and checks the output list against per-source thresholds. If any check fails it logs a
`WARNING` (or optionally raises, depending on a `--strict` flag).

**Checks to implement:**

1. **Minimum job count** — if count drops below threshold, the facet GUIDs probably changed or
   the API returned an error body instead of postings.
1. **Description completeness** — `% with non-empty description ≥ threshold`. Catches JSON key
   path regressions.
1. **Description minimum length** — catches cases where description is technically non-empty
   but only contains boilerplate (e.g. a single whitespace or paragraph).
1. **`posted_at` format** — all values must match `YYYY-MM-DD`. Catches cases where the
   relative-date parser fails on a new Workday string format.
1. **Location validity** — no values matching `\d+ Locations`. Catches the multi-location
   fallback breaking.
1. **Salary mention rate** — warn if fewer than expected % of descriptions mention `$` or
   `salary`. A sudden drop likely means the description body structure changed.

**Where to put it:** `src/job_scraper/quality.py` — a `QualityReport` dataclass and a
`check(jobs, thresholds)` function. Wire it into the CLI `run-config` command after the scrape
returns, before writing the JSONL.

**Per-source thresholds:** Define in a `THRESHOLDS` dict keyed by `source_name`, with a
generic fallback for new scrapers. Could also be expressed in the YAML config.

______________________________________________________________________

### Layer 2 — Fixture-based contract tests (catches code regressions in CI)

Save a small real API response snapshot (one page, 2–3 postings, with full `jobPostingInfo`
detail responses) as a test fixture JSON file. Run it through the scraper's parsing logic in
CI without hitting the network.

**What this catches that unit tests don't:**

The existing mocks in `test_sel.py` use hand-crafted minimal dicts. A fixture using a real
response catches:

- New fields Workday starts returning that break our parsing assumptions
- Field renames (e.g. if `bulletFields` became `bulletField`)
- Nested structure changes (e.g. if `jobPostingInfo` moved to a different key)

**Where to put it:**

- Fixture: `tests/fixtures/sel_jobs_response.json` + `tests/fixtures/sel_detail_response.json`
- Test: `tests/job_scraper/test_sel_contract.py`

**How to capture the fixture:** Run a one-off script that hits the live API with `limit=2`,
saves both the listing response and one detail response to the fixture files, and commits them.
Re-capture periodically (or when a regression is detected) to keep the fixture fresh.

______________________________________________________________________

## What is NOT in scope

- Alerting / notifications — just log warnings for now; add email/Slack later if needed.
- Automatic re-scraping on failure — out of scope; human reviews the warning and re-runs.
- Comparing across scrape runs (dedup / delta detection) — separate concern, not part of this
  spec.

______________________________________________________________________

## Where we left off

- The SEL scraper is fully working and producing clean data as of 2026-05-14.
- The `_parse_posted_at` helper and multi-location fallback are implemented and tested.
- All 94 jobs have valid ISO dates, clean locations, and populated descriptions.
- The quality gate and fixture contract tests described above do **not yet exist**.
- The next engineer to pick this up should start with `src/job_scraper/quality.py` (Layer 1),
  since that gives the most value per line of code and runs on every scrape automatically.
