# job_scraper

This is the ingestion layer — it talks to job boards, normalises every posting into a common shape, scrubs PII, and writes append-only JSONL files that the rest of the pipeline reads.

______________________________________________________________________

## How it fits in

```
job_scraper (this module)
    ↓  data/raw/YYYY-MM-DD/        (with --run-date; flat data/raw/ otherwise)
prefilter router
    ↓  data/prefiltered/YYYY-MM-DD/
remote_filter agent
    ↓  data/filtered/YYYY-MM-DD/ or data/trash/YYYY-MM-DD/
skills scorer  →  dispatch
```

You run the scraper, it dumps raw JSONL, and downstream routing/agent stages pick it up from there. Nothing is coupled — you can rerun any phase independently.

______________________________________________________________________

## Scrapers

There are five scraper backends. Each one implements the same two-method interface (`scrape() → list[JobPosting]`, `source_name → str`) so the rest of the pipeline treats them identically.

| Backend        | What it hits                                                                           | Best for                                                            |
| -------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| **LinkedIn**   | LinkedIn guest API (no login)                                                          | Keyword searches, remote filter built-in                            |
| **JobSpy**     | Indeed, ZipRecruiter, and others via [python-jobspy](https://github.com/Bunsly/JobSpy) | Broad multi-board keyword coverage                                  |
| **Greenhouse** | `boards.greenhouse.io/<token>/jobs`                                                    | Companies you specifically target                                   |
| **Lever**      | `jobs.lever.co/<company>`                                                              | Companies you specifically target                                   |
| **Ashby**      | `jobs.ashbyhq.com/<company>`                                                           | Companies you specifically target                                   |
| **SEL**        | Workday CXS API (`selinc.wd1.myworkdayjobs.com`)                                       | Schweitzer Engineering Laboratories — location/worker-type filtered |

The ATS scrapers (Greenhouse / Lever / Ashby) pull **all open roles** from a company board — no keyword filter. That's intentional: you see everything and the remote filter + scorer handle triage downstream.

______________________________________________________________________

## The output: `JobPosting`

Every scraper returns a list of `JobPosting` dataclasses (defined in `models.py`). They all serialize to the same JSONL shape:

```json
{
  "source": "greenhouse:stripe",
  "source_job_id": "12345",
  "source_url": "https://boards.greenhouse.io/stripe/jobs/12345",
  "title": "Data Engineer",
  "company": "Stripe",
  "location": "US-Remote (35 miles+ outside an office)",
  "posted_at": "2026-05-10T00:00:00",
  "description": "**About the role**\n\n- Build data pipelines\n- Work with product teams",
  "scraped_at": "2026-05-13T09:12:00",
  "scrub_counts": {"email": 0, "phone": 0},
  "search_params": {"keywords": "data engineer", "workplace": "remote"},
  "dedup_hash": "abc123..."
}
```

`dedup_hash` is a SHA-256 of `source|source_job_id|company|title|location` (lowercased). It's what within-source dedup and the downstream analysis cache are keyed on. `source` and `source_job_id` are part of the key because re-posts of the same title at the same company/location for different teams or cohorts (notably SEL) are legitimately distinct postings; including them avoids stale-analysis collisions. Tradeoff: a single listing mirrored across multiple sources is no longer collapsed by this hash — a separate fuzzy-match step is the right place for cross-source dedup.

______________________________________________________________________

## PII scrubbing

Every HTML description fragment is normalised to Markdown before storage so bullets, paragraph breaks, and emphasis survive without storing raw markup. Every description is then passed through `pii.scrub()` before being written to disk. It redacts email addresses (`[EMAIL_REDACTED]`) and phone numbers (`[PHONE_REDACTED]`). The `scrub_counts` field records how many of each were removed — useful for spotting boards that leak contact info.

______________________________________________________________________

## Running it

### Single command

```bash
# LinkedIn keyword search
uv run job-scraper-9000 linkedin "data engineer" --workplace remote --save

# Greenhouse board — all open roles at Stripe
uv run job-scraper-9000 greenhouse stripe --save

# Lever board
uv run job-scraper-9000 lever deepmind --save

# Ashby board
uv run job-scraper-9000 ashby mistral --save

# Multi-board (Indeed, ZipRecruiter, etc.)
uv run job-scraper-9000 jobspy "AI engineer" --location USA --save

# SEL (Schweitzer Engineering Laboratories)
uv run job-scraper-9000 sel --location pullman_wa --save
```

`--save` writes to `data/raw/YYYY-MM-DD_HH-MM_<source>_<keywords>.jsonl`. Without it, output goes to stdout.

### YAML config (recommended for daily runs)

`load_config()` parses the YAML into a flat `list[BaseScraper]` — one entry per keyword search and one per ATS board. `run-config` then iterates through that list serially, calling `.scrape()` on each and writing its output immediately before moving to the next. A failure on one scraper is caught and logged; the rest of the list continues.

```bash
uv run job-scraper-9000 run-config config/search.yml --save --run-date 2026-05-19
```

`--run-date YYYY-MM-DD` writes all outputs to `data/raw/YYYY-MM-DD/` instead of the flat `data/raw/` directory. Omit it to use the flat layout. Dry-run to preview the full scraper list without hitting any APIs:

```bash
uv run job-scraper-9000 run-config config/search.yml --dry-run
```

______________________________________________________________________

## YAML config format

```yaml
global:
  default_max_results: 50   # applies to all searches unless overridden
  hours_old: 48             # ignore postings older than this
  linkedin_time: week       # "day" | "week" | "month"
  salary_floor_k: 120       # filter LinkedIn results to $120k+

linkedin:
  workplace: remote         # "remote" | "hybrid" | "onsite"
  job_type: fulltime
  experience: "2,3,4,5"    # LinkedIn experience codes (2=entry … 5=director)
  searches:
    - keywords: "data engineer"
    - keywords: "AI engineer"
      salary_floor_k: 140   # per-search override

jobspy:
  sites: indeed,zip_recruiter
  searches:
    - search_term: "data engineer"
      location: "${HOME_LOCATION}"   # expands from .env

# ATS boards — pulls all open roles, no keyword filter
greenhouse:
  boards:
    - anthropic
    - stripe

lever:
  companies:
    - deepmind

ashby:
  companies:
    - mistral

# Shorthand: looks up each company in config/company_boards.json
# and creates the right scraper automatically
companies:
  - notion
  - perplexity
```

`${HOME_LOCATION}` and any other `${VAR}` references are expanded from environment variables at load time. If a variable isn't set, the config fails loudly rather than silently using a wrong value.

______________________________________________________________________

## Finding which ATS a company uses

Before you can add a company to `greenhouse:`, `lever:`, or `ashby:`, you need to know which board they're on. The `discover` command probes all three and records the result:

```bash
uv run job-scraper-9000 discover anthropic mistral cohere notion
```

It prints a summary and writes to `config/company_boards.json`. After that you can use the `companies:` shorthand in your YAML config and the scraper picks the right backend automatically.

______________________________________________________________________

## Permanent failure skip list

If a scraper hits a 403/404/410 response, it writes an entry to `config/known_failures.json` and skips that source on all future `run-config` runs. This prevents one dead ATS board from blocking the whole batch. You can inspect or clear entries in that file manually — it's plain JSON.

Transient errors (rate limits, 5xx) are **not** recorded; they just get logged as warnings and the run moves on.

______________________________________________________________________

## Module layout

```
job_scraper/
  models.py          # JobPosting dataclass
  pii.py             # email/phone scrubbing
  query.py           # typed query dataclasses (LinkedIn, JobSpy, SEL)
  config.py          # YAML config loader → list[BaseScraper]
  cli.py             # argparse CLI wiring
  _maps.py           # string → enum maps (workplace, job_type, time)
  discover.py        # ATS discovery logic
  company_boards.py  # load/save config/company_boards.json
  skip_list.py       # permanent failure tracking
  scrapers/
    base.py          # BaseScraper ABC
    linkedin.py
    jobspy.py
    greenhouse.py
    lever.py
    ashby.py
    sel.py           # Schweitzer Engineering Labs (Workday CXS API)
```
