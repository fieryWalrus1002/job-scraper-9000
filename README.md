# job-scraper-9000

An automated, modular Python pipeline for scraping, filtering, and scoring job postings against a target candidate profile. Built to run daily and surface only the roles worth looking at.

## What this is trying to do

The full pipeline has five phases:

1. **Ingestion** — Scrape LinkedIn, Indeed, ZipRecruiter, Glassdoor, and direct ATS boards (Greenhouse, etc.) for target keyword searches. Deduplicate across sources using a composite hash of company + title + location.
2. **Pre-filtering** — Scan raw descriptions for blacklist keywords ("hybrid", "onsite", "office 1 day"). Fast pass on clean postings, route flagged ones to local triage.
3. **Local triage (Ollama)** — Send flagged descriptions to a local LLM. Distinguish genuine remote-flexible roles from deceptive hybrid listings. Returns a binary PASS/TRASH decision with a short rationale. Runs on local hardware (RTX 4090).
4. **Cloud scoring (API)** — Batch-send surviving postings to a cloud LLM (OpenAI / Anthropic). Score each against the candidate profile — Python, C++, data/AI engineering, LLMOps, infra-as-code, legacy refactoring, computer vision/UAV/GIS. Returns a weighted score 1–100.
5. **Dispatch** — Query for scores above 60, sort, and send a daily hotlist to Discord or Slack.

**Current state:** Phase 1 (scraper library) is built and tested. The rest of the pipeline is coming.

---

## Setup

```bash
uv sync
```

---

## CLI

After `uv sync`, the `job-scraper` command is available:

```text
uv run job-scraper <SCRAPER> <keywords> [options]

Scrapers: linkedin | jobspy | greenhouse
```

### Output modes

All subcommands write to **stdout by default** (good for piping to `jq`). Two flags change that:

| Flag | Behaviour |
| --- | --- |
| *(none)* | Write JSONL to stdout |
| `--save` | Write to `data/raw/YYYY-MM-DD_<source>_<keywords>.jsonl` |
| `-o FILE` | Write to a specific file path |

`--save` and `-o` are mutually exclusive.

### linkedin

Hits the LinkedIn guest API directly — no login, no browser.

```bash
# Stdout — pipe to jq for quick inspection
uv run job-scraper linkedin "LLM Ops" --no-descriptions --max-results 5 | jq '.title + " @ " + .company'

# Save to data/raw/ with auto-naming
uv run job-scraper linkedin "LLM Ops" --time day --salary 120 --max-results 50 --save

# Full options
uv run job-scraper linkedin --help
```

Options:

| Flag | Default | Notes |
| --- | --- | --- |
| `--time` | `day` | `day`, `week`, `month`, `any` |
| `--workplace` | `remote` | `remote`, `onsite`, `hybrid` |
| `--job-type` | `fulltime` | `fulltime`, `parttime`, `contract` |
| `--experience` | `2,3,4,5` | 1=intern 2=entry 3=assoc 4=mid-senior 5=director 6=exec |
| `--salary FLOOR_K` | — | `40`, `60`, `80`, `100`, `120` (thousands) |
| `--max-results` | `25` | |
| `--no-descriptions` | — | Skips fetching full descriptions — much faster |

### jobspy

Wraps [python-jobspy](https://github.com/Bunsly/JobSpy) — scrapes LinkedIn, Indeed, ZipRecruiter, Glassdoor, and Google Jobs in one call.

```bash
uv run job-scraper jobspy "data engineer" --hours-old 48 --sites linkedin,indeed --save

uv run job-scraper jobspy --help
```

Options:

| Flag | Default | Notes |
| --- | --- | --- |
| `--sites` | `linkedin,indeed,zip_recruiter` | Comma-separated |
| `--location` | `USA` | |
| `--hours-old` | `24` | |
| `--no-remote` | — | Removes the remote filter |
| `--enforce-annual-salary` | — | Only postings with an annual salary listed |
| `--max-results` | `25` | Per-site |

### greenhouse

Hits the Greenhouse public JSON API for a company's ATS board — no Selenium needed.

```bash
# board token is the slug in boards.greenhouse.io/<token>
uv run job-scraper greenhouse anthropic --save
uv run job-scraper greenhouse stripe | jq '.title'
```

### run-config

Runs every search defined in a YAML config file in a single invocation — the intended mode for scheduled/cron use.

```bash
# Validate the config and print what would run (no network calls)
uv run job-scraper run-config config/example-search-config.yml --dry-run

# Run everything, save all results to one file in data/raw/
uv run job-scraper run-config config/example-search-config.yml --save

# Or write to a specific path
uv run job-scraper run-config config/example-search-config.yml -o jobs.jsonl
```

If any individual scraper fails (rate limit, network error, etc.) the error is logged and the rest of the run continues.

---

## Search config (YAML)

Define all your searches in one place. See [config/example-search-config.yml](config/example-search-config.yml) for a complete reference.

```yaml
global:
  default_max_results: 50
  hours_old: 48           # used by jobspy
  linkedin_time: week     # day | week | month | any
  salary_floor_k: 120     # thousands — 40 / 60 / 80 / 100 / 120

linkedin:
  experience: "4,5"       # 4=mid-senior, 5=director
  workplace: remote
  job_type: fulltime
  searches:
    - keywords: "LLM Ops"
    - keywords: "MLOps engineer"
      salary_floor_k: 80  # per-search override

jobspy:
  sites: linkedin,indeed,zip_recruiter
  no_remote: false
  searches:
    - search_term: "data engineer"
      location: "Pullman, WA"   # per-search override
    - search_term: "MLOps"      # defaults to location: USA

greenhouse:
  boards:
    - anthropic
    - openai
    - palantir
```

### Override precedence

```text
scraper class defaults  <  global section  <  scraper section  <  per-search entry
```

### Per-search overrides

| Scraper | Overridable per search |
| --- | --- |
| `linkedin` | `keywords` (required), `time`, `workplace`, `job_type`, `experience`, `salary_floor_k`, `max_results` |
| `jobspy` | `search_term` (required), `location`, `sites` (replaces section value), `hours_old`, `max_results` |
| `greenhouse` | n/a — boards are a flat list |

### Validation

`load_config` raises `ConfigError` immediately on invalid values — before any network calls are made. Invalid `linkedin_time`, unknown jobspy `sites`, bad `salary_floor_k`, missing required fields, etc. are all caught at parse time. Use `--dry-run` to validate a config before scheduling it.

---

## Data landing zone

Scraped files land in `data/raw/` and are named:

```text
data/raw/YYYY-MM-DD_<source>_<keywords>.jsonl
```

Examples:

```text
data/raw/2026-05-11_linkedin_llm-ops.jsonl
data/raw/2026-05-11_jobspy_data-engineer.jsonl
data/raw/2026-05-11_greenhouse-anthropic_anthropic.jsonl
```

The directory is tracked in git; the `.jsonl` files are gitignored. The downstream pipeline stages (filtering, LLM scoring) will read from this directory.

Inspect with `jq`:

```bash
jq '.' data/raw/2026-05-11_linkedin_llm-ops.jsonl     # pretty-print all
jq '.title + " @ " + .company' data/raw/*.jsonl        # titles across all files
jq 'select(.description | test("remote"; "i"))' data/raw/*.jsonl
```

### Cron setup

To run daily at 7am and drop results into the landing zone:

```cron
0 7 * * * cd /path/to/job-scraper-9000 && uv run job-scraper linkedin "LLM Ops" --save >> /var/log/job-scraper.log 2>&1
0 7 * * * cd /path/to/job-scraper-9000 && uv run job-scraper jobspy "LLM Ops" --save >> /var/log/job-scraper.log 2>&1
```

---

## Python API

All scrapers are also usable directly in code:

```python
from job_scraper import LinkedInJobScraper, LinkedInSearchQuery, TIME_DAY

scraper = LinkedInJobScraper(LinkedInSearchQuery(keywords="LLM Ops", time_posted=TIME_DAY))
jobs = scraper.scrape()
```

```python
from job_scraper import JobSpyScraper
from job_scraper.scrapers.jobspy import JobSpyQuery

scraper = JobSpyScraper(JobSpyQuery(search_term="LLM Ops", hours_old=24))
jobs = scraper.scrape()
```

```python
from job_scraper import GreenhouseScraper
from job_scraper.scrapers.greenhouse import GreenhouseQuery

scraper = GreenhouseScraper(GreenhouseQuery(board_token="anthropic"))
jobs = scraper.scrape()
```

Fan out across all sources:

```python
scrapers = [
    LinkedInJobScraper(LinkedInSearchQuery(keywords="LLM Ops", time_posted=TIME_DAY)),
    JobSpyScraper(JobSpyQuery(search_term="LLM Ops", hours_old=24)),
    GreenhouseScraper(GreenhouseQuery(board_token="anthropic")),
]
all_jobs = [job for s in scrapers for job in s.scrape()]
```

---

## Project structure

```text
src/job_scraper/
  models.py          # JobPosting dataclass + dedup hash
  pii.py             # Email/phone redaction (scrub())
  query.py           # LinkedInSearchQuery + time/salary/experience constants
  cli.py             # job-scraper CLI entry point
  scrapers/
    base.py          # BaseScraper ABC
    linkedin.py      # Guest API — no login, no Selenium
    jobspy.py        # python-jobspy wrapper (LinkedIn/Indeed/ZipRecruiter/Glassdoor/Google)
    greenhouse.py    # Greenhouse ATS public JSON API

data/raw/            # Scraped JSONL files land here (gitignored)
scrape-it.py         # Standalone script entry point (configure and run directly)
simple-scrape.py     # Original single-file prototype (reference)
tests/               # 47 tests, all scrapers mocked at the HTTP layer
```

---

## Tests

```bash
uv run pytest tests/ -v
```

---

## LinkedIn query parameter reference

| Parameter | Values |
| --- | --- |
| `time_posted` | `TIME_DAY` (24h), `TIME_WEEK` (7d), `TIME_MONTH` (30d), `TIME_ANY` |
| `workplace` | `"1"` on-site, `"2"` remote, `"3"` hybrid |
| `job_type` | `"F"` full-time, `"P"` part-time, `"C"` contract |
| `experience` | `"1"` intern, `"2"` entry, `"3"` associate, `"4"` mid-senior, `"5"` director, `"6"` exec |
| `salary_floor` | `40_000`, `60_000`, `80_000`, `100_000`, `120_000` |
| `sort_by` | `"DD"` most recent, `"R"` relevance |
