# Email Scraper → Pipeline: orchestrator + pile writer

**Status:** Ratified 2026-06-18. Local-only personal tooling (not part of the
cloud pipeline — it reads a personal inbox).

## 1. Problem

ZipRecruiter alert emails are a personal, local-only job source. We can turn them
into `JobPosting` records, but two gaps block real use:

1. **Freshness is load-bearing.** Measured across 100 emails: ZR's `/km/` tracking
   tokens expire **exactly 96h after send**. Past that, links are dead and nothing
   enriches. The workflow must be age-aware so the (headful, Cloudflare-piggyback)
   browser budget is spent only on emails that can still yield descriptions.
1. **No handoff to the pipeline.** `process_eml_directory` returns a
   `list[JobPosting]` but never persists it. Every other scraper writes
   `data/raw/[run_date/]*.jsonl`, which `prefilter` consumes. Email jobs must land
   in that same pile.

Goal: one local command that pulls fresh emails → enriches via the real Chrome
profile → writes only the **enriched** jobs into `data/raw/` in the same format the
other scrapers use.

**Decisions:** enriched-only pile · pull→enrich→pile in one run · profile/headful
by default.

> **Consumer caveat (verified 2026-06-18):** `data/raw/` is read by the standalone
> **`prefilter` CLI** flow (`src/prefilter/cli.py` → `data/raw/<run_date>` →
> remote_filter → skills_fit). It is **not** read by `just run-overnight`, which is
> DB-driven and live-scrapes its own sources (`pipeline/worker.py default_scrape_fn`)
> — it never touches `data/raw`. Wiring email jobs into the overnight/app path is an
> open follow-up (see below).

## 2. Integration contract (verified)

- Pile format: `jobs_cli._common._output(jobs, dest)` writes `json.dumps(asdict(j))`
  per line; `_auto_path(source, keywords, run_date)` →
  `data/raw/[run_date/]{ts}_{source}_{slug}.jsonl`. `JobPosting` is a dataclass, so
  `enrichment_status` rides along in `asdict`. (`_output` does **not** mkdir — the
  caller must.)
- Consumer: `prefilter` reads `data/raw/{run_date}` (or flat) — `src/prefilter/cli.py:15`
  — and loads each line as a **plain dict** (`src/prefilter/router.py:94`), so the
  extra field is harmless; no downstream change.
- Grabber: `download_labeled_emails_as_eml(service, output_dir, max_emails)` +
  `get_gmail_service()` in `gmail_eml_grabber.py`.
- Profile piggyback already wired: `ZR_SCRAPER_PROFILE_DIR` / `ZR_SCRAPER_HEADLESS`
  via `zr_scraper._profile_settings`.

## 3. Changes

### 3.1 `src/email_scraper/pile.py` — "final pile" writer (thin reuse)

`write_pile(jobs, run_date=None) -> Path | None` reuses `_auto_path` + `_output`
with `source="ZipRecruiter_Email"`, `keywords="email-alerts"`; mkdirs the parent;
empty list → log + return None (no empty file). Uses the scrapers' own writer, not
a parallel one.

### 3.2 `process_eml_directory.py` — age gate

Add `max_age_hours: float | None`; helper `_email_sent_at(msg)` via
`parsedate_to_datetime` (assume UTC if naive). Skip + log (`aged-out`) emails older
than the cutoff before enriching, so we never launch the browser on an all-expired
email. CLI: `--max-age-hours` / `--include-stale`.

### 3.3 `src/email_scraper/orchestrator.py` — orchestrator (+ `__main__`)

`run(...)`:

1. **Pull** (unless `--no-pull`): `download_labeled_emails_as_eml(...)`.
1. **Profile-by-default**: unless `--headless`, set `ZR_SCRAPER_PROFILE_DIR`
   (`--profile-dir`, default `~/.config/google-chrome`) + `ZR_SCRAPER_HEADLESS=0`.
   **Fail-fast pre-flight**: if Chrome is running (`pgrep -x chrome`), abort (profile
   lock would crash the run).
1. **Enrich**: `process_eml_directory(scrape_details=True, max_age_hours=96 unless --include-stale, run_date=..., archive_processed=--archive)`.
1. **Filter + summarize**: keep `enrichment_status == ENRICHED`; log a status
   histogram (enriched / external_ats / expired / unenriched / aged-out).
1. **Write pile**: `write_pile(enriched, run_date)`; log path + count.
   Run: `uv run python src/email_scraper/orchestrator.py`. `--run-date` defaults to
   today, matching `overnight --run-date`.

### 3.4 Tests (`tests/email_scraper/`)

`test_pile.py` (path/asdict line/empty), `test_orchestrator.py` (enriched-only
filter, histogram, `--no-pull`, Chrome-running abort), age-gate in
`test_process_eml_directory`. All network/Playwright/grabber mocked.

## 4. Reaching the app — `email-overnight` pipeline (shipped)

The `data/raw` pile only feeds the standalone `prefilter` CLI (viewer-only). To
land email jobs in the **app** the same way `run-overnight` does, a separate
single-user pipeline reuses the overnight stages:

- `src/pipeline/email_overnight.py` — `run_email_pipeline(...)`: load the
  provisioned user (Azure DB) → materialize their run dir → `enrich_email_jobs()`
  (Chrome profile) → write the enriched jobs as a synthetic `ziprecruiter_email`
  scrape stage + `enqueue`/`mark_succeeded` (bypassing `claim_next`, which isn't
  run_id-scoped) → `consolidate_run` → `classify_consolidated` → `score_run`.
- Output: `data/pipeline_runs/<run_id>/<slug>/skills_fit/scored.jsonl` with a
  dedicated `<date>T<HHMM>-email` run id — identical to overnight. Then the
  **existing** `just upload-blob <run-id>` ships it (KEDA → ingest → app).
- CLI: `job-scraper-9000 email-overnight --user-email <you>`; recipe
  `just run-email <you>`. Stops at the local run (no auto-upload).
- Preconditions (same as overnight): user provisioned in the Azure DB (profile +
  search config + remote policy); `classify`/`score` invoke the LLM agents (cost —
  use `--max-jobs` for smoke runs); Chrome closed (profile lock); don't run
  concurrently with an overnight (shared `pipe.*`).

### Still out of scope

- skills_fit skipping null-description records (moot while pile is enriched-only).
- The `data/raw` pile → `prefilter` local flow stays as the offline/analysis path.
- No `pyproject.toml` / `uv.lock` / infra changes; no new deps.

## 5. Verification

1. `uv run pytest tests/email_scraper/ -q` green; ruff clean.
1. Live, Chrome closed: `uv run python src/email_scraper/orchestrator.py --no-pull --run-date $(date +%F)` → `data/raw/<date>/<ts>_ZipRecruiter_Email_email-alerts.jsonl`.
1. `head -1` → JSON dict, non-null `description`/`posted_at`, `enrichment_status:"enriched"`.
1. `prefilter` ingests that run-date (extra field ignored).

## 6. Dedup + the enrich/score seam (shipped 2026-06-18)

### Why

ZR rotates the tracking token every send, so the same job arrives in many emails
with a different URL (measured: 30% of jobs repeat, one 18×). Our derived
`source_job_id` was per-send, so `dedup_hash` was unstable — meaning repeat LLM
spend (the `AnalysisCache`s missed) and one job showing up as up to 18 rows in the
app (`raw.job_postings ON CONFLICT (dedup_hash) DO NOTHING`).

### Stable id via `listing_key`

A `/km/` link redirects to `/jobs/v2/<base64>` whose payload is
`{"listing_key": ...}` — stable per listing. `_fetch_with_playwright` now returns
the post-redirect `final_url`; `enrich_job_url` decodes the `listing_key`
(`_extract_listing_key`) and the parser uses it as `source_job_id`. This makes
`dedup_hash` stable, so the **existing** `remote_filter` + `skills_fit`
`AnalysisCache`s hit on repeats (no repeat LLM cost) and the app/consolidate dedup
correctly — *no new "Layer 2" code was needed.*

### Layer 1 — processed-email cache

`seen_store.py` is a `SeenStore` **port** with a `JsonlSeenStore` adapter
(`data/cache/email_processed.jsonl`, keyed by Gmail message-id = filename stem).
`process_eml_directory` skips already-handled emails and records each attempt
regardless of outcome. `--no-cache` bypasses (also on `email-overnight`, for retry).

### Enrich/score seam

`enrich_email_jobs()` is the DB-free core. `email-enrich` (new CLI) writes
`enriched.jsonl` on any worker; `email-overnight --enriched-input <file>` (recipe
`just score-email`) scores a pre-enriched file with no re-enrichment. Lets the
slow, $0 enrichment run on a cheap node while the paid LLM stages stay centralized.

### Contract note

`posted_at` is a **date** (`YYYY-MM-DD`) — `ScoredJobPosting.posted_at: date`
rejects datetimes. The email scraper emits date-only (`_date_only`), matching every
other scraper.

## 7. Future plans (deferred — not built)

These make sense only once enrichment actually runs on more than one box. The code
above makes them possible without committing to the machinery now.

- **Central cache adapter.** Promote `SeenStore` from local JSONL to a shared
  Postgres table (a container on the Proxmox LAN, or Azure) so distributed nodes
  coordinate — a new adapter behind the existing port, callers unchanged.
- **Detached-node autonomy (snapshot/delta).** Rather than nodes dialing the DB,
  a stage-0 export of the seen-keyset → rsync to the node → it works offline and
  emits a delta the workstation reconciles (`ON CONFLICT DO NOTHING`). Ports &
  adapters means this is a `SnapshotSeenStore` + `cache-pull`/`cache-push` CLIs.
- **Per-node Cloudflare profiles.** The real gating cost of distribution: each
  worker needs its own `cf_clearance`-cleared Chrome profile, seeded and refreshed.
  This — not the code — is why the fleet is "when ready," not now.
- **skills_fit null-description skip.** Moot while the pile/scored set is
  enriched-only; revisit if email-only records are ever ingested.
