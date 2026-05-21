# job-scraper-9000

An automated pipeline that scrapes job postings from every major source, uses LLM agents to classify remote-work policy and match jobs to your skills, then delivers a curated daily shortlist of roles actually worth reading.

Built as a personal job-hunting tool and as a learning project to experiment with multi-agent systems.

---

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

### 4. Dispatch

- Deliver the hot list via email or a custom web GUI (FastAPI).
- Future: browser extension calling a backend LLM agent to fill DOM fields for applications.

---

**Current state:** Phases 1 and 1.5 are complete. The Phase 2 remote-filter implementation and eval framework are complete; golden dataset balancing and precision tuning are in progress (current baseline: accuracy 0.8654 / precision 0.7073 / recall 0.9355 / F1 0.8056 on 104 records). Phase 3 (Skills Fit) is in progress: schema, ordinal eval harness (ordinal-agreement + top-k metrics), keyword baseline, real rubric prompt, and v4 candidate profile are in place; seed gold set is being built via teacher-first HITL (frontier teacher proposes labels, human ratifies/overrides through a per-record markdown review). See [specs/skills_fit_agent_plan.md](specs/skills_fit_agent_plan.md) and [src/agents/skills_fit/README.md](src/agents/skills_fit/README.md).

The remote filter agent is evaluated against a human-verified gold dataset built through a teacher/HITL workflow: a stronger cloud model proposes remote-policy labels, then the Streamlit review UI confirms or corrects them. Eval runs record dataset hashes, prompt hashes, config, git metadata, metrics, and mismatch files so prompt/model changes can be compared reproducibly. Future local-model distillation can build on this gold layer; see [specs/teacher-student.md](specs/teacher-student.md) for the design.

Work tracked on GitHub — `gh issue list` or https://github.com/fieryWalrus1002/job-scraper-9000/issues

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
uv run job-scraper run-config config/search.yml --save --run-date $(date +%F)
```

**Run the prefilter router:**

```bash
uv run job-scraper prefilter --run-date $(date +%F)
```

**Run the remote filter:**

```bash
uv run job-scraper remote-filter --run-date $(date +%F)
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

---

## Tech stack

| Layer | Tools |
| --- | --- |
| Scraping | [python-jobspy](https://github.com/Bunsly/JobSpy), direct ATS APIs (Greenhouse, Lever, Ashby), LinkedIn guest API |
| Local inference | Ollama — Qwen 2.5 14B, Llama 3.1 8B (RTX 4090) |
| Cloud inference | OpenAI API (gpt-4o-mini default; gpt-4o for teacher) |
| Review UI | Streamlit |
| Data | Append-only JSONL, medallion layout (raw → prefiltered/local/trash → staging → eval) |
| Runtime | Python 3.13, `uv`, Pydantic v2 |

---

## Deeper docs

| Topic | Doc |
| --- | --- |
| Project status — what's built, what's next | `gh issue list` or https://github.com/fieryWalrus1002/job-scraper-9000/issues |
| Prefilter router — deterministic routing layer, config, CLI | [src/prefilter/README.md](src/prefilter/README.md) |
| Prefilter router design — deterministic routing layer before remote filter | [specs/prefilter_design.md](specs/prefilter_design.md) |
| Prefilter implementation plan — branch-ready build plan | [specs/prefilter_implementation_plan.md](specs/prefilter_implementation_plan.md) |
| Scraper module — how it works, backends, YAML config format | [src/job_scraper/README.md](src/job_scraper/README.md) |
| Scraper CLI — all commands, flags, YAML config | [src/agents/README.md](src/agents/README.md) |
| Remote filter agent — config, commands, classification schema | [src/agents/remote_filter/README.md](src/agents/remote_filter/README.md) |
| Skills fit agent — ordinal scoring, profile contract, teacher-first HITL | [src/agents/skills_fit/README.md](src/agents/skills_fit/README.md) |
| Skills fit plan — schema, calibration, sequencing (Phase R / G / B) | [specs/skills_fit_agent_plan.md](specs/skills_fit_agent_plan.md) |
| Teacher-student distillation design | [specs/teacher-student.md](specs/teacher-student.md) |
| Batch pipeline scripts — prepare, merge, sample | [scripts/README.md](scripts/README.md) |
| Eval scripts — running evals, CLI flags, comparing runs | [scripts/README.md#eval](scripts/README.md#eval) |
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
  raw/                # scraped JSONL (Bronze, source truth)
  prefiltered/        # jobs routed onward to remote_filter
  local/              # local jobs held aside from remote_filter
  staging/            # teacher-annotated, awaiting review (Silver)
  eval/               # human-verified golden dataset (Gold)
  filtered/           # remote_filter pass results
  trash/              # prefilter and remote_filter rejects
```
