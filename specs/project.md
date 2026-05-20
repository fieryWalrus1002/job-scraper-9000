# job-scraper-9000

An automated pipeline that scrapes job postings from every major source, uses LLM agents to classify remote-work policy and match jobs to a candidate profile, then delivers a curated daily shortlist. Cuts a firehose of listings down to roles actually worth reading.

Built as a personal job-hunting tool and a learning project for multi-agent systems.

## Pipeline

1. **Ingestion** — Scrape LinkedIn, Indeed, ZipRecruiter, Glassdoor, and direct ATS boards (Greenhouse, Lever, Ashby). Deduplicate across sources using a composite hash of company + title + location.
2. **Prefilter** — Deterministic routing layer: country gate, local allowlist, obvious reject signals. No LLM cost for clear cases.
3. **Remote Filter Agent** — LLM classifies each remaining posting: genuinely remote-flexible vs. deceptive hybrid. Returns PASS/TRASH with rationale.
4. **Skills Fit Agent** — Scores PASS jobs against a candidate profile (technical overlap, level alignment, domain context). Returns `fit_score`, `verdict`, `top_matches`, `gaps`.
5. **Dispatch** — Delivers the ranked shortlist via email or a local FastAPI web UI.

## Keywords

model evaluation · telemetry · prompt engineering · few-shot · human-in-the-loop · Infrastructure-as-Code

## Status

Work tracked on GitHub — `gh issue list` or https://github.com/fieryWalrus1002/job-scraper-9000/issues
