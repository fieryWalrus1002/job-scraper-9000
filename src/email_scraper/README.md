# Email Scraper

Utilities for turning job-alert emails into `JobPosting` objects that match the rest of the scraper pipeline.

Current scope is ZipRecruiter job-alert emails downloaded from Gmail as `.eml` files. I get so dang
many of them, might as well try to extract some value! The email body contains almost everything except
for the description, so we need to scrape the detail page for that. The scraper is pretty basic and doesn't handle Cloudflare blocks or non-ZR ATS pages, but it does detect and log those cases.

## Data flow

```text
Gmail API
  -> gmail_eml_grabber.py
  -> data/emails/scraped/*.eml
  -> process_eml_directory.py
  -> zr_parser.py
  -> optional zr_scraper.py detail enrichment
  -> list[job_scraper.models.JobPosting]
```

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

If `scrape_details=True`, it calls `zr_scraper.fetch_job_details_from_url()` for each parsed job to try to enrich:

- full description
- posted date

### `zr_scraper.py`

Browser-based detail-page scraper using Playwright.

Direct one-URL test:

```bash
uv run python src/email_scraper/zr_scraper.py "https://www.ziprecruiter.com/..."
```

It prints whether `posted_at` and `description` were found.

## Important limitations

ZipRecruiter email links are not always stable ZipRecruiter job pages.

Observed cases:

1. **External ATS redirects**

   - Example destinations include Oracle Cloud / company ATS pages.
   - `zr_scraper.py` currently follows redirects, but only knows how to parse ZR-style detail pages.
   - If the destination ATS returns an error or uses an unsupported page shape, enrichment returns `(None, None)`.

1. **Cloudflare challenge pages**

   - ZR may return a `Just a moment...` challenge page.
   - The scraper detects this and logs it, but does not bypass it reliably.

When enrichment fails, the parser still returns the email-derived job record with `description=None` and `posted_at=None`.

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

- Add a generic detail-scraper router that chooses a parser based on final URL host.
- Add ATS-specific detail scrapers for common platforms such as Oracle Cloud, Workday, Greenhouse, Lever, Ashby, and SmartRecruiters.
- Add a cache for detail-scrape results so repeated email processing does not repeatedly open the same URLs.
- Wire the returned `JobPosting` list into the existing ingest/dedup pipeline.
