# job-scraper-9000

An automated pipeline that scrapes job postings from every major source, uses LLM agents to classify remote-work policy and match jobs to your skills, then delivers a curated daily shortlist of roles actually worth reading.

Built as a personal job-hunting tool and as a learning project to experiment with multi-agent systems.

---

## Pipeline

The full pipeline has four phases:

### 1. Ingestion

- Scrape LinkedIn, Indeed, ZipRecruiter, Glassdoor, and direct ATS boards (Greenhouse, Lever, Ashby) for target keyword searches.
- Deduplicate across sources using a composite hash of company + title + location.

### 2. Remote Filter Agent

- Send each description to the Remote Filter Agent (OpenAI Agents Framework).
- Distinguish genuine remote-flexible roles from deceptive hybrid listings. Returns a binary PASS/TRASH decision with a short rationale.
- Runs on local hardware (RTX 4090).

### 3. Skills Fit Scoring Agent

- Batch-send surviving postings to a cloud LLM (OpenAI / Anthropic) or local Ollama instance.
- Score each against a candidate profile using a structured rubric:
  - **Technical overlap** — does the stack match core expertise (C++, Python, AI, data engineering)?
  - **Level alignment** — senior/lead role, or entry level?
  - **Domain context** — involves engineering, automation, or deep learning where experience is deep?
- Returns structured JSON with `fit_score`, `top_matches`, `gaps`, `verdict`.

### 4. Dispatch

- Deliver the hot list via email or a custom web GUI (FastAPI).
- Future: browser extension calling a backend LLM agent to fill DOM fields for applications.

---

**Current state:** Phases 1 and 2 are production-ready. Phase 3 (scoring) and Phase 4 (dispatch) are coming.

The remote filter agent is being improved via a teacher-student distillation pattern — a cloud teacher model builds a labeled dataset that trains a faster local student model. See [specs/teacher-student.md](specs/teacher-student.md) for the design.

---

## Setup

Requires Python 3.13+ and [`uv`](https://github.com/astral-sh/uv).

```bash
uv sync
cp .env.example .env   # fill in API keys
```

`.env` variables:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required for remote_filter (OpenAI) and teacher batch runs |
| `LLM_PROVIDER` | `openai` (default) or `ollama` |
| `LLM_MODEL` | Model override — defaults to `gpt-4o-mini` / `qwen2.5:14b` |
| `OLLAMA_BASE_URL` | Ollama endpoint — defaults to `http://localhost:11434/v1` |
| `HOME_LOCATION` | Expands `${HOME_LOCATION}` in YAML search configs |
| `USER_LOCATION` | Used in remote_filter geographic restriction checks (default: `USA`) |

---

## Quick start

**Scrape jobs:**

```bash
uv run job-scraper run-config config/search.yml --save
```

**Run the remote filter:**

```bash
python scripts/run_remote_filter.py
```

**Run the teacher batch pipeline + HITL review:**

More details in [the HITL README.md](src/review_ui/README.md).

```bash
python scripts/prepare_batch.py        # build OpenAI batch request file
# upload data/raw/gpt_teacher_batch.jsonl → OpenAI, download results
python scripts/merge_batch_results.py  # merge results into staging
streamlit run src/review_ui/app.py     # open the review UI
```

---

## Tech stack

| Layer | Tools |
| --- | --- |
| Scraping | [python-jobspy](https://github.com/Bunsly/JobSpy), direct ATS APIs (Greenhouse, Lever, Ashby), LinkedIn guest API |
| Local inference | Ollama — Qwen 2.5 14B, Llama 3.1 8B (RTX 4090) |
| Cloud inference | OpenAI API (gpt-4o-mini default; gpt-4o for teacher) |
| Review UI | Streamlit |
| Data | Append-only JSONL, medallion layout (raw → staging → eval) |
| Runtime | Python 3.13, `uv`, Pydantic v2 |

---

## Deeper docs

| Topic | Doc |
| --- | --- |
| Project status — what's built, what's next | [project-status.md](project-status.md) |
| Scraper module — how it works, backends, YAML config format | [src/job_scraper/README.md](src/job_scraper/README.md) |
| Scraper CLI — all commands, flags, YAML config | [src/agents/README.md](src/agents/README.md) |
| Remote filter agent — config, commands, classification schema | [src/agents/remote_filter/README.md](src/agents/remote_filter/README.md) |
| Teacher-student distillation design | [specs/teacher-student.md](specs/teacher-student.md) |
| Batch pipeline scripts — prepare, merge, sample | [scripts/README.md](scripts/README.md) |
| HITL review UI — how it works, input format, gold layer output | [src/review_ui/README.md](src/review_ui/README.md) |

---

## Tests

```bash
uv run pytest
```

---

## Project structure

```text
src/
  job_scraper/        # scraper library + CLI
  agents/             # LLM agents (remote_filter, future: scorer, dispatcher)
  review_ui/          # Streamlit HITL review app

scripts/              # one-off data pipeline scripts (prepare, merge, sample)
prompts/              # LLM system prompts
config/               # search configs, agent policy, company board database
specs/                # design docs

data/
  raw/                # scraped JSONL (Bronze)
  staging/            # teacher-annotated, awaiting review (Silver)
  eval/               # human-verified golden dataset (Gold)
  filtered/           # remote_filter pass results
  trash/              # remote_filter rejected results
```
