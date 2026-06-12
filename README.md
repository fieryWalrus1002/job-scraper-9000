# job-scraper-9000

An automated pipeline that scrapes job postings from every major source, uses LLM agents to classify remote-work policy and match jobs to your skills, then delivers a curated daily shortlist of roles actually worth reading.

Built as a personal job-hunting tool and as a learning project to experiment with multi-agent systems.

______________________________________________________________________

## Pipeline

The full pipeline has four phases, plus a deterministic routing step between ingestion and remote filtering:

### 1. Ingestion

- Scrape LinkedIn, Indeed, ZipRecruiter, Glassdoor, and direct ATS boards (Greenhouse, Lever, Ashby) for target keyword searches.
- Deduplicate across sources using a composite hash of company + title + location.
- Preserve `data/raw/` as the immutable source-truth scrape output.

### 1.5 Prefilter Router

- Deterministically route raw jobs before spending LLM calls.
- Send obvious remote-ish / ambiguous jobs to the Remote Filter Agent.
- Route clearly local jobs to a separate local lane.
- Reject obvious non-US or clearly non-viable jobs early.

### 2. Remote Filter Agent

- Send routed candidates to the Remote Filter Agent (OpenAI Agents Framework).
- Distinguish genuine remote-flexible roles from deceptive hybrid listings. Returns a binary PASS/TRASH decision with a short rationale.
- Runs on local hardware (RTX 4090).

### 3. Skills Fit Scoring Agent

- Batch-send surviving postings to a cloud LLM (OpenAI / Anthropic) or local Ollama instance.
- Score each against a versioned candidate profile (`config/profile/candidate_profile.yml`) using an ordinal 1-5 rubric:
  - **Technical overlap** — does the core stack match (C++, Python, applied ML, data engineering)?
  - **Level alignment** — senior/lead role, or entry level?
  - **Domain context** — engineering, automation, scientific instrumentation, or deep learning?
- Returns structured JSON with `fit_score` (1-5), `confidence`, `score_rationale`, `top_matches`, `gaps`, and `hard_concerns`. `fit_score` is the verdict; there is no separate `verdict` field.

### 4. Dispatch & UI

- Deliver the daily hotlist through a dedicated full-stack web dashboard.
- Serve processed data via a RESTful **FastAPI** layer, consumed by a modern **React + TypeScript** frontend.
- Review LLM reasoning, view metrics, and inspect skills-fit gap analyses visually rather than parsing raw text streams.

______________________________________________________________________

**Current state:** Phases 1 and 1.5 are complete. The Phase 2 remote-filter implementation and eval framework are complete; golden dataset balancing and precision tuning are in progress (current baseline: accuracy 0.8654 / precision 0.7073 / recall 0.9355 / F1 0.8056 on 104 records). Phase 3 (Skills Fit) — Phase R baseline is closed: schema, ordinal eval harness (ordinal-agreement + top-k metrics), keyword baseline, real rubric prompt, the v5 candidate profile, and a 21-record human-ratified seed gold set are all committed. The pinned champion run is recorded in [`config/eval/champions.yml`](config/eval/champions.yml). Phase G (calibration loop, one-lever-per-PR) is the active phase. See [specs/skills_fit_agent_plan.md](specs/skills_fit_agent_plan.md) and [src/agents/skills_fit/README.md](src/agents/skills_fit/README.md).

The remote filter agent is evaluated against a human-verified gold dataset built through a teacher/HITL workflow: a stronger cloud model proposes remote-policy labels, then the Streamlit review UI confirms or corrects them. Eval runs record dataset hashes, prompt hashes, config, git metadata, metrics, and mismatch files so prompt/model changes can be compared reproducibly. Future local-model distillation can build on this gold layer; see [specs/teacher-student.md](specs/teacher-student.md) for the design.

Work tracked on GitHub — `gh issue list` or <https://github.com/fieryWalrus1002/job-scraper-9000/issues>

______________________________________________________________________

## Setup

Requires Python 3.13+ and [`uv`](https://github.com/astral-sh/uv).

```bash
uv sync
cp .env.example .env   # fill in your secrets
```

`.env` holds secrets and per-machine values (API keys, your home location). See [`.env.example`](.env.example) for the canonical list with inline comments. Non-secret **operator** config (LLM provider/model/URL, policy thresholds, prompts) lives in YAML under `config/`, not `.env`.

**Per-user search targeting and candidate profiles live in Postgres** (Phase 12), not in committed YAML. Users edit their own through the in-app Settings page; the admin can seed them from filled-in templates with `scripts/push_user_config.py`. The pipeline itself never reads the DB — `scripts/pull_user_configs.py` materializes each user's config to `runs/<user>/{search.yml,candidate_profile.yml}`, the same YAML shapes the scraper and skills-fit agent already consume. See [specs/configs_in_db_design.md](specs/configs_in_db_design.md).

______________________________________________________________________

## Quick start

The umbrella CLI is `job-scraper-9000`. The older `job-scraper` name remains
as a supported alias and points at the same entrypoint.

**Scrape jobs:**

```bash
uv run job-scraper-9000 run-config config/search.yml --save --run-date $(date +%F)
```

**Run the prefilter router:**

```bash
uv run job-scraper-9000 prefilter --run-date $(date +%F)
```

**Run the remote filter:**

```bash
uv run job-scraper-9000 remote-filter --run-date $(date +%F)
```

**Run evals:**

```bash
uv run scripts/run_remote_filter_eval.py --workers 4
uv run scripts/compare_evals.py --last 5
```

**Run lower-cost OpenAI Batch eval:**

```bash
uv run python scripts/submit_eval_batch.py --run-id gpt4o_mini_batch
uv run python scripts/poll_eval_batch.py
```

**Run the teacher batch pipeline + HITL review:**

More details in [the HITL README.md](src/review_ui/README.md).

```bash
python scripts/prepare_batch.py        # build OpenAI batch request file
# upload data/raw/gpt_teacher_batch.jsonl → OpenAI, download results
python scripts/merge_batch_results.py  # merge results into staging
streamlit run src/review_ui/app.py     # open the review UI
```

**Run the skills fit agent:**

```bash
uv run job-scraper-9000 skills-fit --run-date $(date +%F)
```

**Review the top matches and gaps for a specific run:**

I added `--limit` and `--start` flags to the `view_top_x_jobs.py` script so you can paginate through results without hitting OOM on your local machine. For example, to view jobs 0-20 from the May 26 run:

```bash
uv run scripts/view_top_x_jobs.py --run-date 2026-05-26 --start 0 --limit 20
```

Should it have been `--start 0 --end 20`? Yes, probably. Or done it as a slice `--range 0:20`. But here we are.

**Schedule a run overnight:**

```bash
at 12:30 AM -f scripts/run_overnight.sh
```

This will schedule the `scripts/run_overnight.sh` script to execute at 12:30 AM. The script should contain the necessary commands to run the full pipeline.

**Run the gold-expansion HITL loop (after reviewing markdown files):**

```bash
# Ingest filled-in review files into the gold set
uv run scripts/parse_skills_fit_review_md.py \
  --review-dir data/staging/skills_fit_review_<date>/ \
  --in data/staging/skills_fit_review_template.jsonl

# Re-run eval on the expanded gold to establish the new baseline
uv run scripts/run_skills_fit_eval.py --scorer llm --run-id "phase_g_v6_gold_expand_<date>"

# Compare against the previous champion
uv run scripts/compare_evals.py --against-champion skills_fit \
  --diff <run-id-from-above> --per-record
```

**Run the Full Stack Local Dev Environment:**

Spins up the FastAPI backend (port 8000) and the Vite frontend (port 5173) concurrently using `honcho`, streaming prefix-labeled logs to a single shell.

```bash
just dev
```

**Run Local Integration Testing (Docker Containers):**

Simulates the multi-target isolated cloud environment using a localized Nginx static asset server and Uvicorn process wrapper.

```bash
docker compose up               # Starts Backend (port 8000) + Production-built Frontend (port 8080)
docker compose run --rm scraper # Triggers a one-off pipeline ingestion run against local data volumes
```

______________________________________________________________________

## Tech stack

| Layer           | Tools                                                                                                             |
| --------------- | ----------------------------------------------------------------------------------------------------------------- |
| Runtime         | Python 3.13, `uv`, Pydantic v2                                                                                    |
| Scraping        | [python-jobspy](https://github.com/Bunsly/JobSpy), direct ATS APIs (Greenhouse, Lever, Ashby), LinkedIn guest API |
| Local inference | llama.cpp — Qwen 3.6 27B (RTX 4090)                                                                               |
| Cloud inference | OpenAI API (gpt-5-mini default; gpt-5.4 for teacher)                                                              |
| Review UI       | Streamlit (HITL Evaluation Interface)                                                                             |
| Data            | Append-only JSONL, medallion layout (raw → prefiltered/local/trash → staging → eval)                              |
| Orchestration   | Docker Compose, `just`, `honcho` (process stream supervisor)                                                      |
| Frontend        | React 19, TypeScript, Vite, shadcn/ui, TanStack Query                                                             |
| Backend API     | FastAPI, Uvicorn (One-process-per-container cloud architecture)                                                   |

______________________________________________________________________

## Deeper docs

| Topic                                                                      | Doc                                                                              |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Project status — what's built, what's next                                 | `gh issue list` or <https://github.com/fieryWalrus1002/job-scraper-9000/issues>  |
| `data/` layout — directory map, writers, schemas                           | [data/README.md](data/README.md)                                                 |
| Prefilter router — deterministic routing layer, config, CLI                | [src/prefilter/README.md](src/prefilter/README.md)                               |
| Prefilter router design — deterministic routing layer before remote filter | [specs/prefilter_design.md](specs/prefilter_design.md)                           |
| Prefilter implementation plan — branch-ready build plan                    | [specs/prefilter_implementation_plan.md](specs/prefilter_implementation_plan.md) |
| Scraper module — how it works, backends, YAML config format                | [src/job_scraper/README.md](src/job_scraper/README.md)                           |
| Scraper CLI — all commands, flags, YAML config                             | [src/agents/README.md](src/agents/README.md)                                     |
| Remote filter agent — config, commands, classification schema              | [src/agents/remote_filter/README.md](src/agents/remote_filter/README.md)         |
| Skills fit agent — ordinal scoring, profile contract, teacher-first HITL   | [src/agents/skills_fit/README.md](src/agents/skills_fit/README.md)               |
| User configs in DB — per-user profile/search, settings form, push/pull     | [specs/configs_in_db_design.md](specs/configs_in_db_design.md)                   |
| Skills fit plan — schema, calibration, sequencing (Phase R / G / B)        | [specs/skills_fit_agent_plan.md](specs/skills_fit_agent_plan.md)                 |
| Teacher-student distillation design                                        | [specs/teacher-student.md](specs/teacher-student.md)                             |
| Batch pipeline scripts — prepare, merge, sample                            | [scripts/README.md](scripts/README.md)                                           |
| Eval scripts — running evals, CLI flags, comparing runs                    | [scripts/README.md#eval](scripts/README.md#eval)                                 |
| HITL review UI — how it works, input format, gold layer output             | [src/review_ui/README.md](src/review_ui/README.md)                               |
| Containerization & Local Integration                                       | [docker/README.md](docker/README.md)                                             |

______________________________________________________________________

## Tests

```bash
uv run pytest
```

______________________________________________________________________

## Project structure

```Plaintext
job-scraper-9000/
├── config/           # Operator config: scraper/agent policy, provider/model (per-user profile + search live in the DB)
├── data/             # Local pipeline file-based medallion workspace
├── docker/           # Multi-target application Dockerfiles (backend, scraper, frontend)
├── frontend/         # Standalone Vite + React client application (TS + shadcn/ui)
├── prompts/          # LLM system prompts
├── specs/            # Architecture blueprints and implementation plans
├── scripts/          # Ingestion pipelines and offline evaluation harnesses
└── src/
    ├── api/          # FastAPI web application layer (endpoints, schemas)
    ├── job_scraper/  # Core scraping framework and custom parsers
    ├── prefilter/    # Deterministic static routing layer (no LLM overhead)
    ├── agents/       # Multi-agent intelligence layers (remote_filter, skills_fit)
    ├── agent_eval/   # Automated grading, metric aggregations, run logging
    ├── user_config/  # Per-user config models + human→pipeline transform (Phase 12)
    └── review_ui/    # Streamlit HITL gold-standard evaluation app
```

`data/` is the local pipeline workspace — directory layout, writers, and schemas are documented in [data/README.md](data/README.md).
