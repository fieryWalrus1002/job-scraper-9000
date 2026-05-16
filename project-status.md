# Project Status

_Last updated: 2026-05-15_

---

- [x] **Phase 1 — Ingestion:** Complete and production-ready.
  - [x] 5 scrapers: LinkedIn (guest API), JobSpy (multi-board), Greenhouse, Lever, Ashby ATS
  - [x] Deduplication via SHA-256 hash of company + title + location
  - [x] PII scrubbing (email, phone) with count tracking
  - [x] YAML config system with env var expansion, per-search overrides, and validation
  - [x] Company board discovery (`discover` command auto-detects ATS per company)
  - [x] Permanent failure skip list (HTTP 403/404/410 persisted to JSON)
  - [x] Pre-commit hooks (ruff check + format, trailing whitespace, YAML validation)
  - [x] GitHub Actions CI (ruff lint + pytest on push and PR)
  - [x] Comprehensive test suite — 12 test files, ~1,700 lines covering all scrapers, CLI, config, PII, discovery

- [ ] **Phase 2 — Remote Filter Agent:** Core complete, eval/provenance loop in progress.
  - [x] Pydantic v2 validation schema (`RemoteAnalysis`) with 8-category classification
  - [x] Agent functional — `analyze_remote()` + `passes_remote_filter()` with structured output
  - [x] Policy fully config-driven via `config/agent/remote_agent.yml` (no code changes needed to retune)
  - [x] Agent unit tests with mocked OpenAI client
  - [x] Batch preparation script (`prepare_batch.py`) — builds OpenAI Batch API request file
  - [x] Batch merge script (`merge_batch_results.py`) — joins teacher results back to original jobs
  - [x] Streamlit HITL review UI — confirm or correct teacher verdicts, writes to gold layer
  - [x] Eval framework basics — run logging, provenance, metrics, mismatch files, and run comparison CLI
  - [ ] Fix prompt provenance mismatch between agent runtime and eval/batch metadata paths
  - [ ] Package/install cleanup — include `src/eval`, `src/utils`, and review UI support modules as needed
  - [ ] Golden dataset expansion/balancing — especially more true-pass remote roles
  - [ ] Eval throughput work — parallel synchronous eval (`--workers`) and OpenAI Batch eval scripts
  - [ ] `uv run agents remote-filter` CLI not wired into `pyproject.toml` — currently run via `scripts/run_remote_filter.py`

- [ ] **Phase 3 — Skills Fit Scoring Agent:** Designed, not started.
  - [ ] Pydantic schema for scoring output (`fit_score`, `top_matches`, `gaps`, `verdict`)
  - [ ] Scoring agent (mirrors remote_filter structure, adjusted rubric)
  - [ ] Batch or streaming inference path

- [ ] **Phase 4 — Dispatch + Deployment:** Not started.
  - [ ] Hotlist delivery — email or FastAPI web GUI
  - [ ] IaC — Bicep + Az CLI for Azure deployment
  - [ ] Scheduled daily trigger (Azure Logic App or similar)
