# Email Scraper

Utilities for turning job-alert emails into `JobPosting` objects that match the rest of the scraper pipeline.

> **Local-only, personal tooling.** This module reads a personal Gmail inbox and is meant to run only on a workstation — it is **not** part of the cloud pipeline. That's why it's free to do local-machine things (reuse a real Chrome profile) that the rest of the repo avoids.

Current scope is ZipRecruiter job-alert emails downloaded from Gmail as `.eml` files. I get so dang
many of them, might as well try to extract some value! The email body contains almost everything except
for the description, so we need to scrape the detail page for that. Enrichment is **best-effort**: a small router classifies each link first and only renders ZR-hosted pages, recording an explicit `enrichment_status` on every record so a missing description is a reasoned state, not a silent `None`.

## Data flow

```text
Gmail API
  -> gmail_eml_grabber.py
  -> data/emails/scraped/*.eml
  -> process_eml_directory.py
  -> zr_parser.py
  -> optional zr_scraper.enrich_job_url() router (classify -> render only ZR pages)
  -> list[job_scraper.models.JobPosting]  (each carries enrichment_status)
  -> pile.write_pile() -> data/raw/[run_date/]*.jsonl  (the pipeline reads this)
```

`orchestrator.py` ties the whole flow together in one command — see below.

## Quick start

```bash
# Pull newest emails, enrich via your Chrome profile, write the pipeline pile.
# Chrome must be CLOSED (profile lock). Enriched-only by default.
uv run python src/email_scraper/orchestrator.py
```

This writes `data/raw/<today>/...jsonl`. **Note:** that pile is consumed by the
standalone `prefilter` CLI flow, **not** by `just run-overnight` (which is
DB-driven and live-scrapes its own sources — it never reads `data/raw`). See
`specs/email_scraper_pipeline.md` for the consumer caveat and the open question of
wiring email jobs into the overnight/app path.

## Configuration

The modules read `config/email_scraper/config.yml`.

Expected keys:

```yaml
credentials_path: "config/email_scraper/secrets/credentials.json"
token_path: "config/email_scraper/secrets/token.json"
label_query: "label:to-scrape/zr"
output_dir: "data/emails/scraped"
archive_dir: "data/emails/archived"
max_emails: 10
```

Notes:

- `credentials_path` and `token_path` are secrets/auth artifacts and should stay out of git.
- `label_query` uses normal Gmail search syntax.
- `max_emails` limits Gmail download and is also the default `.eml` processing limit.

## Modules

### `gmail_eml_grabber.py`

Downloads the newest matching Gmail messages as raw `.eml` files.

```bash
uv run python src/email_scraper/gmail_eml_grabber.py
```

Override the count for one run:

```bash
uv run python src/email_scraper/gmail_eml_grabber.py --max-emails 2
```

Output files are named by Gmail message id:

```text
data/emails/scraped/<gmail-message-id>.eml
```

### `process_eml_directory.py`

Reads `.eml` files, extracts the `text/plain` MIME payload, parses jobs, and optionally archives successfully processed files.

Normal run:

```bash
uv run python src/email_scraper/process_eml_directory.py
```

Parser-only smoke test, no browser scraping:

```bash
uv run python src/email_scraper/process_eml_directory.py --max-files 1 --max-jobs 1 --no-scrape
```

Print parsed job URLs without scraping details:

```bash
uv run python src/email_scraper/process_eml_directory.py --max-files 1 --no-scrape --print-jobs
```

Test one job by index from the parsed email:

```bash
uv run python src/email_scraper/process_eml_directory.py --max-files 1 --job-index 2
```

Archive successfully parsed `.eml` files:

```bash
uv run python src/email_scraper/process_eml_directory.py --archive-processed
```

Archives go to `archive_dir` from config, currently:

```text
data/emails/archived
```

### `zr_parser.py`

Parses ZipRecruiter email plaintext into `JobPosting` objects.

Extracted from the email body:

- title
- source URL
- source job id where possible
- company
- location
- salary min/max/period where present

If `scrape_details=True`, it calls `zr_scraper.enrich_job_url()` for each parsed job to try to enrich:

- full description
- posted date

and records the resulting `enrichment_status` on the `JobPosting`.

### `zr_scraper.py`

The detail-enrichment router plus the Playwright-based ZR page scraper.

- `enrich_job_url(url) -> (description, posted_at, status)` — the entry point the parser uses. It classifies the link **before** any network/browser cost and only renders ZR-hosted pages.
- `classify_zr_url(url) -> (kind, expired)` — pure URL inspection.
- `fetch_job_details_from_url(url) -> (description, posted_at)` — the ZR-only Playwright render + parse (JSON-LD first, DOM fallback).

Direct one-URL test:

```bash
uv run python src/email_scraper/zr_scraper.py "https://www.ziprecruiter.com/..."
```

It prints the `enrichment_status` and whether `posted_at` / `description` were found.

### `orchestrator.py`

The top-level workflow: pull → enrich → write the pipeline pile. Defaults are
tuned for the real use (get descriptions): it uses your Chrome profile headful,
skips emails past the 96h window, and writes **only enriched** jobs.

```bash
uv run python src/email_scraper/orchestrator.py            # full run
uv run python src/email_scraper/orchestrator.py --no-pull  # reprocess local .eml
uv run python src/email_scraper/orchestrator.py --no-pull --max-jobs 3  # quick bounded run
```

Key flags: `--no-pull` (skip Gmail download), `--include-stale` (ignore the 96h
gate), `--headless` (no profile; ZR `/km/` will hit Cloudflare), `--profile-dir`,
`--archive`, `--run-date`, `--max-files` / `--max-jobs`. It aborts up front if
Chrome is running (the profile lock would crash the launch).

### `pile.py`

`write_pile(jobs, run_date)` writes the enriched jobs to
`data/raw/[run_date/]<ts>_ZipRecruiter_Email_email-alerts.jsonl` by reusing the
scrapers' own writer (`jobs_cli._common`), so email postings are identical in
shape to every other source. `prefilter` reads that directory directly.

## Dedup

ZR rotates the tracking token every send, so the same job in two emails arrives
with a different URL (and a different derived id). Two things keep that from
becoming wasted work and duplicate app rows:

- **Stable id (`listing_key`).** During enrichment we decode the resolved
  `/jobs/v2/<base64>` URL → `{"listing_key": ...}` and use it as `source_job_id`,
  so `dedup_hash` is stable across sends. That makes the existing `remote_filter`
  and `skills_fit` `AnalysisCache`s hit on repeats (no repeat LLM spend) and lets
  the app dedup correctly (one frontend row, not one per send).
- **Layer-1 processed-email cache** (`seen_store.py`). A `SeenStore` keyed by Gmail
  message-id (`data/cache/email_processed.jsonl`) skips whole emails already
  handled — recorded regardless of outcome. `--no-cache` to bypass. The `SeenStore`
  is a port; a central Postgres adapter (Proxmox LAN / Azure) can drop in later for
  cross-node coordination without touching callers.

## Distributed enrichment (the enrich/score seam)

Enrichment (slow, $0, no DB) is split from scoring (DB + paid LLM) so the
expensive-but-cheap-to-parallelize half can run anywhere:

```bash
# On any worker (workstation / Proxmox VM / Pi5) — DB-free, cloud-free:
uv run job-scraper-9000 email-enrich -o enriched.jsonl
# rsync enriched.jsonl back to a DB-connected box, then:
uv run job-scraper-9000 email-overnight --user-email <you> --enriched-input enriched.jsonl
```

The worker needs only a Cloudflare-cleared Chrome profile — no DB creds, no Azure.
(`email-overnight` with no `--enriched-input` still does the all-in-one run.)

## Enrichment statuses

ZipRecruiter email links are not always renderable ZR job pages, so enrichment is best-effort. Every record gets one of these (`None` only when `scrape_details=False`, i.e. never attempted):

| Status         | Meaning                                                                                                                                                      |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `enriched`     | Reached a ZR page and got a description and/or posted date.                                                                                                  |
| `external_ats` | `/ekm/` link hands off to the employer's own ATS (Oracle, Workday, …). Not scraped — email-only by policy; no browser launched.                              |
| `expired`      | The email tracking token's `expires` timestamp has passed; the link is dead. No fetch.                                                                       |
| `unenriched`   | A ZR page was reached but yielded nothing — Cloudflare `Just a moment…` challenge, an upstream `500`, or an unrecognized DOM. The specific reason is logged. |

One deliberate non-goal: we don't build per-ATS scrapers for the `/ekm/` hand-offs — that's a maintenance treadmill. Those stay email-only by policy. The email-derived fields (title, company, location, salary, source URL) are always populated regardless of enrichment outcome.

### The 96-hour window

Measured across 100 emails: ZR's `/km/` tracking tokens carry an `expires` timestamp **exactly 96 hours (4 days) after the email is sent**. After that the link is dead and enrichment can't even be attempted. So process alerts within ~3 days of arrival, or the ZR-hosted half is all `expired`. (`_select_eml_files` processes newest-first by file mtime, which matches "grab and process promptly".)

### Getting past Cloudflare (the profile piggyback)

A live `/km/` link redirects to a `/jobs/v2/` page that sits behind a Cloudflare "Just a moment…" challenge. A throwaway headless browser faces that challenge cold every run and loses (`unenriched`). A **real Chrome profile** sails through, because it reuses the `cf_clearance` cookie you already earned by browsing ZR manually — the same reason the link "just works" when you click it from Gmail.

Since this module is local-only, that's a fine way to run it. Opt in with env vars (kept off by default so the headless path and tests stay hermetic):

```bash
# Chrome must be closed (profile lock), or point at a copy / dedicated profile.
export ZR_SCRAPER_PROFILE_DIR="$HOME/.config/google-chrome"   # or a copy
uv run python src/email_scraper/process_eml_directory.py --max-files 1
```

| Env var                  | Effect                                                                                                                   |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `ZR_SCRAPER_PROFILE_DIR` | Chrome user-data-dir to reuse. Unset = throwaway headless context (default).                                             |
| `ZR_SCRAPER_HEADLESS`    | Truthy forces headless even with a profile. Default with a profile is headful (headless is the easiest Cloudflare tell). |

The `zr_scraper.py` CLI also takes `--profile-dir` / `--headful` for one-off tests. Caveats: it depends on a clearance cookie that expires, so it's inherently flaky and will occasionally re-challenge — when it does, browse to a ZR job page in that profile once to refresh clearance.

## Fast iteration workflow

Use this when debugging parser/scraper behavior:

1. Download only a few emails:

   ```bash
   uv run python src/email_scraper/gmail_eml_grabber.py --max-emails 1
   ```

1. List parsed jobs without scraping:

   ```bash
   uv run python src/email_scraper/process_eml_directory.py --max-files 1 --no-scrape --print-jobs
   ```

1. Pick one index and test only that URL:

   ```bash
   uv run python src/email_scraper/process_eml_directory.py --max-files 1 --job-index 3
   ```

1. If needed, test the raw URL directly:

   ```bash
   uv run python src/email_scraper/zr_scraper.py "https://www.ziprecruiter.com/..."
   ```

## Future work

Likely next steps:

- Measure the real `/km/` enrichment hit-rate on a fresh batch (tokens expire, so old test emails undercount it) to decide whether ZR-email is worth keeping as a description source at all.
- Add a cache for detail-scrape results so repeated email processing does not repeatedly open the same URLs.
- Wire the returned `JobPosting` list into the existing ingest/dedup pipeline; teach skills_fit to skip records whose `enrichment_status` left them without a description.
- Only if one ATS dominates real volume: add a single handler for it behind the existing router (not a speculative fleet).
