# Project Implementation Status

An automated pipeline that scrapes job postings, uses LLM agents to classify remote-work policy and match jobs to skills, then presents a curated daily shortlist.

---

## Phase 1 — Ingestion ✅

Scrape LinkedIn, Indeed, ZipRecruiter, Glassdoor, and direct ATS boards (Greenhouse, Lever, Ashby). Deduplicate across sources using a composite hash of company + title + location.

| Task | Status |
| --- | --- |
| Scraper library | ✅ done |
| Pre-commit hooks (lint/formatting) | ✅ done |
| GitHub Actions (tests on push/PR) | ✅ done |

---

## Phase 2 — Remote Filter Agent 🔄

Distinguish genuine remote-flexible roles from deceptive hybrid listings. Returns a binary PASS/TRASH decision with a short rationale. Runs on local hardware (RTX 4090).

| Task | Status |
| --- | --- |
| Pydantic validation schema | ✅ done |
| Agent functional (OpenAI framework) | ✅ done |
| Teacher batch pipeline + HITL review UI | ✅ done |
| Golden dataset assembled | 🔄 in progress (8 pass / 42 trash → target 25 pass) |
| Eval framework | 🔄 in progress — see [eval_impl_status.md](eval_impl_status.md) |

---

## Phase 3 — Skills Fit Scoring Agent ⬜

Batch-send surviving postings to a cloud LLM or local Ollama instance. Score each against candidate profile: technical overlap, level alignment, domain context. Returns structured JSON with `fit_score`, `top_matches`, `gaps`, `verdict`.

| Task | Status |
| --- | --- |
| Pydantic schema design | ⬜ todo |
| Agent implementation | ⬜ todo |
| Eval framework (reuse Phase 2 scaffolding) | ⬜ todo |

---

## Phase 4 — Dispatch ⬜

Deliver the hot list via email or FastAPI web GUI. Future: browser extension calling backend LLM agent to fill DOM fields.

| Task | Status |
| --- | --- |
| FastAPI dispatch service | ⬜ todo |
| Azure deployment (Bicep / Az CLI IaC) | ⬜ todo |
