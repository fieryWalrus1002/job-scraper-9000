# job-scraper-9000

An automated pipeline that scrapes job postings from every major source, uses LLM agents to classify remote-work policy and match jobs to a candidate profile, then delivers a curated daily shortlist. Cuts a firehose of listings down to roles actually worth reading.

Built as a personal job-hunting tool and a learning project for multi-agent systems.

## Pipeline

1. **Ingestion** — Scrape LinkedIn, Indeed, ZipRecruiter, Glassdoor, and direct ATS boards (Greenhouse, Lever, Ashby). Deduplicate across sources using a composite hash of company + title + location.
2. **Prefilter** — Deterministic routing layer: country gate, local allowlist, obvious reject signals. No LLM cost for clear cases.
3. **Remote Filter Agent** — LLM classifies each remaining posting: genuinely remote-flexible vs. deceptive hybrid. Returns PASS/TRASH with rationale.
4. **Skills Fit Agent** — Scores PASS jobs against a candidate profile (technical overlap, level alignment, domain context). Returns `fit_score`, `verdict`, `top_matches`, `gaps`.
5. **Dispatch** — Delivers the ranked shortlist via email or a local FastAPI web UI.

## Orchestration

The pipeline stages are intentionally decoupled — each reads from and writes to an explicit dated partition (`data/*/<YYYY-MM-DD>/`), so any stage can be rerun independently. Orchestration is a separate concern layered on top:

**v1 — manual / bash script**
Run stages in order by hand during development. Once stable, wrap in a single shell script:
```bash
DATE=$(date +%F)
uv run job-scraper run-config config/search.yml --save --run-date $DATE
uv run job-scraper prefilter --run-date $DATE
uv run job-scraper remote-filter --run-date $DATE
uv run job-scraper skills-fit --run-date $DATE
```

**v2 — cron**
Cron the shell script for fully hands-off daily runs. Add `set -e` and pipe stderr to an email or log file for alerting on failures.

**v3 — Azure Container App Job**
Managed cron execution in the cloud. The script stays identical; the runner moves off the local machine. Pairs with the Azure Bicep infra work (GitHub issue #22).

**Not planned: Airflow / Prefect**
Overkill for a single-machine, single-user daily pipeline. Each stage is already idempotent and file-isolated — the filesystem *is* the DAG. Revisit only if the pipeline grows to multiple parallel runs or multiple users, or if I get bored and want to learn Airflow/Prefect for fun.

## Keywords

model evaluation · telemetry · prompt engineering · few-shot · human-in-the-loop · Infrastructure-as-Code

## Status

Work tracked on GitHub — `gh issue list` or https://github.com/fieryWalrus1002/job-scraper-9000/issues
