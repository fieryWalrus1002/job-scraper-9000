# job-scraper-9000

An automated, modular Python pipeline for scraping, filtering, and scoring job postings against a target candidate profile. Built to run daily and surface only the roles worth looking at.

## What this is trying to do

The full pipeline has five phases:

1. **Ingestion** — Scrape LinkedIn, Indeed, ZipRecruiter, Glassdoor, and direct ATS boards (Greenhouse, Lever, Ashby) for target keyword searches. Deduplicate across sources using a composite hash of company + title + location.
2. **Pre-filtering** — Scan raw descriptions for blacklist keywords ("hybrid", "onsite", "office 1 day"). Fast pass on clean postings, route flagged ones to local triage.
3. **Local triage (Ollama)** — Send flagged descriptions to a local LLM. Distinguish genuine remote-flexible roles from deceptive hybrid listings. Returns a binary PASS/TRASH decision with a short rationale. Runs on local hardware (RTX 4090).
4. **Cloud scoring (API)** — Batch-send surviving postings to a cloud LLM (OpenAI / Anthropic). Score each against the candidate profile — Python, C++, data/AI engineering, LLMOps, infra-as-code, legacy refactoring, computer vision/UAV/GIS. Returns a weighted score 1–100.
5. **Dispatch** — Query for scores above 60, sort, and send a daily hotlist to Discord or Slack.

**Current state:** Phase 1 (scraper library) and Phase 2 (remote-filter agent) are built and tested. Phases 3–5 are coming.

---

## Setup

```bash
uv sync
cp .env.example .env   # then fill in any API keys
```

`.env` values used at runtime:

| Variable | Used by |
| --- | --- |
| `HOME_LOCATION` | Available for `${HOME_LOCATION}` expansion in YAML configs |
| `OPENAI_API_KEY` | remote_filter agent (default provider) |
| `LLM_PROVIDER` | `openai` (default) or `ollama` |
| `LLM_MODEL` | Model override — defaults to `gpt-4o-mini` (OpenAI) or `qwen2.5:14b` (Ollama) |
| `OLLAMA_BASE_URL` | Ollama endpoint — defaults to `http://localhost:11434/v1` |
| `USER_LOCATION` | User location for restriction checks in remote_filter — defaults to `USA` |

---

## CLI

After `uv sync`, the `job-scraper` command is available:

```text
uv run job-scraper <COMMAND> [options]

Commands: linkedin | jobspy | greenhouse | lever | ashby | discover | run-config
```

### Output modes

All scraper subcommands write to **stdout by default** (good for piping to `jq`). Two flags change that:

| Flag | Behaviour |
| --- | --- |
| *(none)* | Write JSONL to stdout |
| `--save` | Write to `data/raw/YYYY-MM-DD_HH-MM_<source>_<keywords>.jsonl` |
| `-o FILE` | Write to a specific file path |

`--save` and `-o` are mutually exclusive.

### linkedin

Hits the LinkedIn guest API directly — no login, no browser.

```bash
# Stdout — pipe to jq for quick inspection
uv run job-scraper linkedin "LLM Ops" --no-descriptions --max-results 5 | jq '.title + " @ " + .company'

# Save to data/raw/ with auto-naming
uv run job-scraper linkedin "LLM Ops" --time day --salary 120 --max-results 50 --save
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
```

Options:

| Flag | Default | Notes |
| --- | --- | --- |
| `--sites` | `linkedin,indeed,zip_recruiter` | Comma-separated. Also: `glassdoor`, `google` |
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

### lever

Hits the Lever public API for a company's job board.

```bash
# company slug is the slug in jobs.lever.co/<slug>
uv run job-scraper lever netflix --save
uv run job-scraper lever stripe | jq '.title'
```

### ashby

Hits the Ashby public API for a company's job board.

```bash
# company slug is the slug in jobs.ashbyhq.com/<slug>
uv run job-scraper ashby mistral --save
uv run job-scraper ashby anthropic | jq '.title'
```

### discover

Finds which ATS board(s) a company uses and saves the result to `config/company_boards.json`. Does **not** scrape jobs — only populates the board database used by the `companies:` config section.

```bash
uv run job-scraper discover anthropic mistral stripe
```

After running, inspect the database:

```bash
cat config/company_boards.json
```

### run-config

Runs every search defined in a YAML config file in a single invocation — the intended mode for scheduled/cron use.

```bash
# Validate the config and print what would run (no network calls)
uv run job-scraper run-config config/search.yml --dry-run

# Run everything, write each scraper's results to data/raw/ as it completes
uv run job-scraper run-config config/search.yml --save
```

Each scraper writes its results immediately on completion (not batched at the end), so partial results are safe even if later scrapers fail. If a scraper returns a permanent failure (403/404/410), the source is recorded in `config/known_failures.json` and skipped on future runs.

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
      location: "${HOME_LOCATION}"   # reads from .env
    - search_term: "MLOps"           # defaults to location: USA

greenhouse:
  boards:
    - anthropic
    - openai

lever:
  companies:
    - netflix
    - stripe

ashby:
  companies:
    - mistral
    - cohere

# Resolved via config/company_boards.json — run 'discover' first
companies:
  - anthropic
  - deepmind
  - scale-ai
```

### Environment variable expansion

Any string value in the config can reference `.env` variables with `${VAR_NAME}`:

```yaml
searches:
  - search_term: "${JOB_KEYWORDS}"
    location: "${HOME_LOCATION}"
```

`load_config` raises `ConfigError` immediately if a referenced variable is not set.

### Override precedence

```text
scraper class defaults  <  global section  <  scraper section  <  per-search entry
```

### Per-search overrides

| Scraper | Overridable per search |
| --- | --- |
| `linkedin` | `keywords` (required), `time`, `workplace`, `job_type`, `experience`, `salary_floor_k`, `max_results` |
| `jobspy` | `search_term` (required), `location`, `sites` (replaces section value), `hours_old`, `max_results` |
| `greenhouse` / `lever` / `ashby` | n/a — company/board lists are flat |

### The `companies:` section

The `companies:` key is a shorthand that looks up each slug in `config/company_boards.json` and dispatches to the correct scraper automatically:

```yaml
companies:
  - anthropic   # → GreenhouseScraper if company_boards.json says "greenhouse"
  - stripe      # → LeverScraper if it says "lever"
  - mistral     # → AshbyScraper if it says "ashby"
```

Run `discover` first to populate `company_boards.json`. Companies not found in the database are warned and skipped.

### Validation

`load_config` raises `ConfigError` immediately on invalid values — before any network calls are made. Invalid `linkedin_time`, unknown jobspy sites, bad `salary_floor_k`, missing required fields, and unset `${VAR}` references are all caught at parse time. Use `--dry-run` to validate before scheduling.

---

## Company board database

`config/company_boards.json` maps company slugs to their ATS board type(s):

```json
{
  "anthropic": ["greenhouse"],
  "mistral":   ["ashby"],
  "stripe":    ["lever", "greenhouse"]
}
```

Build it with `discover`, then reference companies by slug in your YAML config under `companies:`. The file is committed to the repo so the mapping persists across machines.

---

## Known failures

`config/known_failures.json` records boards that returned a permanent error (403/404/410). Entries are skipped automatically on future `run-config` runs with a warning log line. To retry a source, remove its entry from the file.

---

## Data landing zone

Scraped files land in `data/raw/` and are named:

```text
data/raw/YYYY-MM-DD_HH-MM_<source>_<keywords>.jsonl
```

Examples:

```text
data/raw/2026-05-11_07-00_linkedin_llm-ops.jsonl
data/raw/2026-05-11_07-00_jobspy_data-engineer.jsonl
data/raw/2026-05-11_07-00_greenhouse-anthropic_anthropic.jsonl
```

The directory is tracked in git; the `.jsonl` files are gitignored. The downstream pipeline stages (filtering, LLM scoring) will read from this directory.

Inspect with `jq`:

```bash
jq '.' data/raw/2026-05-11_07-00_linkedin_llm-ops.jsonl    # pretty-print all
jq '.title + " @ " + .company' data/raw/*.jsonl             # titles across all files
jq 'select(.description | test("remote"; "i"))' data/raw/*.jsonl
```

### Cron setup

```cron
0 7 * * * cd /path/to/job-scraper-9000 && uv run job-scraper run-config config/search.yml --save >> /var/log/job-scraper.log 2>&1
```

---

## Python API

All scrapers are usable directly in code:

```python
from job_scraper import LinkedInJobScraper, LinkedInSearchQuery, TIME_DAY

scraper = LinkedInJobScraper(LinkedInSearchQuery(keywords="LLM Ops", time_posted=TIME_DAY))
jobs = scraper.scrape()
```

```python
from job_scraper.scrapers.jobspy import JobSpyScraper, JobSpyQuery

scraper = JobSpyScraper(JobSpyQuery(search_term="LLM Ops", hours_old=24))
jobs = scraper.scrape()
```

```python
from job_scraper.scrapers.greenhouse import GreenhouseScraper, GreenhouseQuery
from job_scraper.scrapers.lever import LeverScraper, LeverQuery
from job_scraper.scrapers.ashby import AshbyScraper, AshbyQuery

jobs = GreenhouseScraper(GreenhouseQuery(board_token="anthropic")).scrape()
jobs = LeverScraper(LeverQuery(company="stripe")).scrape()
jobs = AshbyScraper(AshbyQuery(company="mistral")).scrape()
```

---

## Agents

### remote_filter

Analyzes job descriptions for remote work policy and filters postings against a configurable policy.

**What it produces:**

- `data/filtered/remote_filter_pass.jsonl` — postings that passed the policy
- `data/trash/remote_filter_trash.jsonl` — rejected postings with a rejection reason

Each output record is the original job JSON enriched with three fields:

```json
"_remote_analysis": { "remote_classification": "fully_remote", "confidence": "high", ... },
"_filter_result":   "pass",
"_filter_reason":   "passed"
```

**Run it locally:**

```bash
# Reads from data/raw/, writes to data/filtered/ and data/trash/
python scripts/run_remote_filter.py
```

**Configure the policy** in [config/agent/remote_agent.yml](config/agent/remote_agent.yml):

```yaml
policy_thresholds:
  disallowed_classifications:
    - "onsite_disguised"
    - "hybrid"
    - "location_restricted"
  travel:
    max_estimated_days_per_year: 15
    prohibited_categories:
      - "remote_with_frequent_travel"
  relocation:
    allow_required_relocation: false
    allow_local_presence_required: false
  uncertainty:
    on_unclear_classification: "reject"   # or "pass"
```

**Remote classifications** the agent produces:

| Classification | Meaning |
| --- | --- |
| `fully_remote` | No office requirement, no material travel |
| `remote_with_quarterly_travel` | Remote, up to ~4 days/year on-site |
| `remote_with_monthly_travel` | Remote, up to ~12 days/year on-site |
| `remote_with_frequent_travel` | Remote but substantial travel required |
| `hybrid` | Scheduled office days per week |
| `onsite_disguised` | Listed as "remote" but requires local presence |
| `location_restricted` | Remote only within a restricted geography |
| `unclear` | Posting doesn't provide enough signal |

**System prompt** lives in [prompts/remote_agent/system_prompt_v1.txt](prompts/remote_agent/system_prompt_v1.txt) — edit there to tune extraction behavior.

**Python API** (for use in an orchestrator):

```python
from agents.remote_filter.utils import analyze_remote, passes_remote_filter, load_raw_jobs

analysis = analyze_remote(job_description)   # returns RemoteAnalysis | None
ok, reason = passes_remote_filter(analysis, config)
```

---

## Project structure

```text
src/
  job_scraper/
    models.py            # JobPosting dataclass + dedup hash
    pii.py               # Email/phone redaction (scrub())
    query.py             # LinkedInSearchQuery + time/salary/experience constants
    cli.py               # job-scraper CLI entry point
    config.py            # YAML config loader + scraper builder
    company_boards.py    # company → board database (load/save/merge)
    discover.py          # Board discovery: direct probing via requests
    skip_list.py         # Permanent failure registry
    _maps.py             # CLI string → API value maps
    scrapers/
      base.py            # BaseScraper ABC (Generic[Q])
      linkedin.py        # Guest API — no login, no Selenium
      jobspy.py          # python-jobspy wrapper (LinkedIn/Indeed/ZipRecruiter/Glassdoor/Google)
      greenhouse.py      # Greenhouse ATS public JSON API
      lever.py           # Lever ATS public JSON API
      ashby.py           # Ashby ATS public JSON API
  agents/
    remote_filter/
      models.py          # RemoteAnalysis Pydantic model
      utils.py           # analyze_remote(), passes_remote_filter(), load_raw_jobs()

prompts/
  remote_agent/
    system_prompt_v1.txt   # Extraction prompt for remote_filter

config/
  example-search-config.yml      # Annotated scraper config reference
  company_boards.json            # Company → ATS board mapping (committed)
  known_failures.json            # Permanent failure registry (local state, gitignored)
  agent/
    remote_agent.yml             # remote_filter policy thresholds

scripts/
  run_remote_filter.py           # Local test runner for the remote_filter agent

data/raw/              # Scraped JSONL files land here (gitignored)
data/filtered/         # remote_filter pass results (gitignored)
data/trash/            # remote_filter rejected results (gitignored)
tests/                 # Scrapers mocked at HTTP layer; agents mocked at OpenAI client layer
```

---

## Tests

```bash
uv run pytest
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
