# Decoupled multi-user cloud ingest via blob

**Status:** Ratified 2026-06-15. Milestone: **Phase 15: Decoupled multi-user
cloud ingest**.

## 1. Problem

Today `just run-overnight` (Justfile) overrides `DATABASE_URL` to the Azure
Postgres server and ingests `raw.job_scores` **inline**, from the home machine,
inside `pipeline.scoring.score_and_ingest_run`. Consequences:

- The home machine must hold a Postgres firewall rule (`HOME_CLIENT_IP`) against
  a VNet/private-endpoint DB (#161) — fragile and an exposure we'd rather drop.
- A single bad record can break a whole user's batch *against prod*: the
  2026-06-12 run hit `UntranslatableCharacter` (a NUL byte in
  `ai_fit.top_matches`) and `magnus@magnuswood.dev`'s 1128 scores never landed
  in the cloud DB. (NUL fix tracked separately on `fix/ingest-strip-nul-bytes`.)

**Goal:** `just overnight` produces per-user scored files under
`data/pipeline_runs/<run_id>/`, an upload step pushes them to the `pending` blob
container, and the in-Azure ACA ingest job (already KEDA blob-triggered) ingests
them — running on the VNet next to the DB, with no home-machine DB write.

## 2. Current state — what already exists

- **ACA Job** `<prefix>-ingest-job` (`infra/modules/ingestJob.bicep`): Event /
  KEDA `azure-blob` trigger on `pending`, `blobCountPerJob=1`, `parallelism=1`,
  runs `python -m ingest.cli --schema-path db/schema.sql --apply-schema --blob-mode`. DB reachable via private endpoint; storage via account-key conn
  string secret. **It's an ACA Job, not a Function App — reuse it.**
- **Storage containers** `pending` / `processed` / `failed`
  (`infra/modules/storageAccount.bicep`); poison-blob dead-lettering already in
  `_ingest_from_blob`.
- **blob-mode ingest** path + CLI tests (#129).
- **Per-record user routing** already supported: `ingest.core.resolve_user_ids`
  reads `row.get("user_email") or default`, and `_extract_row` carries
  `user_email` (`test_extract_row_carries_user_email`). The producer just never
  stamps it.

So the consumer side is essentially built. The missing work is producer + glue.

## 3. Gaps

- **G1 — Upload is stale/single-user.** `upload-blob` uploads
  `data/scored/{{DATE}}/skills_fit_scored.jsonl` (retired single-user path). The
  multi-user pipeline writes one scored file per user (location normalized in
  §4).
- **G2 — No user attribution in the data.** Scored records carry no
  `user_email`. blob-mode applies one global `--user-email` to *all* pending
  blobs, and the ACA Job command passes none → `resolve_user_ids` raises →
  dead-letter. Stamp `user_email` per record so blobs self-route.
- **G3 — Overnight ingests directly.** `score_and_ingest_run` always ingests
  into the live conn. Need a produce-only mode so the blob path is the cloud
  write. (Note: overnight still needs Azure DB read/queue access for
  orchestration — only the `job_scores` write moves to blob.)
- **G4 — Legacy `db/schema.sql` never retired (#173 open).** Alembic owns the
  schema at runtime (migrations in `migrations/versions/`, latest `0010`, applied
  on API lifespan startup), yet `db/schema.sql` still exists and is still wired
  in: a *required* `--schema-path` arg + `ensure_schema()` in the ingest CLI, the
  ACA Job's `--apply-schema` (`ingestJob.bicep:80`), and a COPY in
  `docker/ingest.Dockerfile`. It can drift from the migrations and re-applies a
  stale DDL on every ingest.
- **G5 — Legacy recipes.** #212: retire/rename single-user `ingest` /
  `upload-blob` / `pipeline` recipes.
- **G6 — Run-artifact layout is wrong on three axes.** (a) The tree is rooted at
  repo root `runs/` instead of under `data/` with the rest of the generated
  data, and collides in name with `data/runs/` (the unrelated RunTracker
  telemetry log). (b) It partitions **user-first** (`runs/<slug>/<run_id>/…`),
  scattering a single run across user dirs and orphaning `.consolidated/` as a
  sibling. (c) `run_id = f"overnight-{run_date}"` (`overnight.py:75`) is
  **date-only**, so a second run the same day clobbers the first's artifacts.
  Additionally the tree conflates *live materialized user config*
  (`runs/<slug>/{search,policies,candidate_profile}.yml`) with *per-run
  artifacts*.

## 4. Run-artifact layout normalization (slice 0 — foundational)

Slice 2's `iter_run_user_outputs` and the blob naming both depend on the
on-disk layout, so this lands **first**. Three moves + a `run_id` fix:

- **Artifacts → `data/pipeline_runs/`, partitioned run-first:**

  ```
  data/pipeline_runs/<run_id>/
    _consolidated/   classified_pass.jsonl  classified_trash.jsonl  postings.jsonl
    <slug>/
      scrape/<source>.jsonl
      skills_fit/input.jsonl  scored.jsonl
  ```

  Run-first co-locates everything for one run (all users + the shared
  consolidated stage), makes the upload/local-ingest walk a trivial
  `<run_id>/*/skills_fit/scored.jsonl`, and makes retention "drop old run dirs."

- **Unique, sortable `run_id`:** include time, not just date — e.g.
  `2026-06-12T1635-overnight` — so same-day reruns don't collide. Reuse the
  existing run timestamp (`overnight.py:182` already stamps `HHMMSS` in the log
  name).

- **Telemetry → `data/run_telemetry/runs.jsonl`** (was `data/runs/`): renaming
  the RunTracker dir kills the `runs/` vs `data/runs/` name collision.

- **Live materialized configs → `data/user_configs/<slug>/`** (split out of the
  artifact tree): these are pulled from the DB and outlive any single run, so
  they don't belong under a run dir.

Filesystem search is single-axis by nature; the **DB stays the index** for
per-user/date queries (postings/scores are already per-user and timestamped) and
RunTracker for per-run cost/telemetry. The tree is just ephemeral working files.

Touches the `runs_dir`/path constants in `planner`, `worker`, `consolidation`,
`scoring`, `overnight` (`DEFAULT_RUNS_DIR`), the RunTracker path, the config
materialization writers (`scripts/pull_user_configs.py`), `.gitignore`, and
`data/README.md`. Mechanical but wide.

## 5. Design

- **Pipeline is strictly produce-only.** Refactor
  `score_and_ingest_run` → `score_run`: it writes
  `data/pipeline_runs/<run_id>/<slug>/skills_fit/scored.jsonl` per user and
  **never** touches `job_scores`. Drop the `ingest_fn` injection and the
  in-pipeline DB score write entirely — no `--direct-ingest` branch. Ingest is
  always a separate concern downstream.
- **Stamp `user_email` into scored records** at write time. The producer (which
  knows `email` per user) is the natural place; makes the output self-routing
  for both the blob path and the local-dev path. Covered by an ingest
  round-trip test.
- **Shared per-run walk.** One helper, `iter_run_user_outputs(run_id)` →
  `(user_email, slug, scored_path)`, feeds both the uploader and the local-dev
  ingest recipe (DRY; one definition of "where a run's per-user outputs live").
- **New `upload-blob` (script + Justfile target)** taking `--run-id`: walk the
  run's per-user outputs and upload each to `pending/<run_id>/<slug>__scored.jsonl`
  (overwrite/idempotent). One blob per user preserves dead-letter failure
  isolation and fans out one KEDA Job execution per user.
- **New local-dev ingest recipe** (separate from the pipeline): walk the run's
  per-user outputs and ingest each into a **local** DB via the existing
  `ingest` CLI. This is how a developer materializes scores locally now that the
  pipeline no longer ingests.
- **ACA Job:** stop relying on a global `--user-email` (records self-route);
  fix the schema source (G4). Image/trigger unchanged otherwise.

## 6. Resolved decisions

- **D1 — Pipeline is produce-only; no in-pipeline ingest at all.** The pipeline
  never writes `job_scores` — it only produces per-user
  `data/pipeline_runs/<run_id>/<slug>/skills_fit/scored.jsonl`.
  `score_and_ingest_run` is
  refactored to a produce-only `score_run` (no `ingest_fn`, no score write, no
  `--direct-ingest` flag). Cloud ingest is the blob → ACA Job path; local-dev
  ingest is a *separate* standalone recipe (existing `ingest` CLI over a local
  DB). The pipeline and ingest are fully decoupled.
- **D2 — Retire `db/schema.sql` entirely; Alembic owns the schema (closes
  #173).** Alembic already migrates on API lifespan startup, so the ingest path
  never needs to apply DDL. This phase deletes the file and rips out everything
  that references it: `ensure_schema()`, the `--schema-path` / `--apply-schema`
  CLI args (both parsers), the ACA Job command flags, and the
  `docker/ingest.Dockerfile` COPY. The ACA Job ingests against an
  already-migrated DB.
- **D3 — Blob auth: uploader on AAD login, Job stays account-key (for now).**
  The uploader runs on a laptop (human + `az login`), which cannot use a managed
  identity, so it uses AAD `--auth-mode login` — no secret on disk; requires the
  **Storage Blob Data Contributor** role on the storage account for the
  operator's identity. The ACA Job keeps its account-key connection string this
  phase (the KEDA `azure-blob` trigger and the in-container blob client both use
  it). Moving the Job to managed identity is a worthwhile follow-up but is an
  auth refactor out of scope here — file as a separate hardening issue (no
  milestone / backlog).
- **D4 — Per-user blob.** One blob per user
  (`pending/<run_id>/<slug>__scored.jsonl`). Records self-route either way, but
  per-user keeps the dead-letter failure isolation and lets the KEDA trigger fan
  out one Job execution per user (`blobCountPerJob=1`) instead of one execution
  swallowing 2–1000 users.
- **D5 — Run-artifact layout (see §4).** Artifacts move to
  `data/pipeline_runs/<run_id>/`, **run-first** partition; RunTracker telemetry
  to `data/run_telemetry/runs.jsonl`; live materialized configs to
  `data/user_configs/<slug>/`; `run_id` becomes unique + sortable
  (`<date>T<time>-<type>`). The DB/RunTracker remain the searchable index; the
  tree is ephemeral working files. Lands first, as slice 0.

## 7. PR slicing (issues filed after ratification)

0. **Normalize the run-artifact layout (§4):** `runs/` → `data/pipeline_runs/`
   run-first; `data/runs/` → `data/run_telemetry/`; live configs →
   `data/user_configs/`; unique sortable `run_id`. Update path constants
   (`planner`, `worker`, `consolidation`, `scoring`, `overnight`), RunTracker,
   config writers, `.gitignore`, `data/README.md`. Foundational — lands first.
1. Refactor `score_and_ingest_run` → produce-only `score_run`: drop the
   in-pipeline `job_scores` write and `ingest_fn` (D1). Pipeline emits files only.
1. Stamp `user_email` into scored records + `iter_run_user_outputs(run_id)`
   helper (+ ingest round-trip test).
1. New multi-user `upload-blob` script + Justfile target over
   `iter_run_user_outputs` (+ test).
1. New local-dev ingest recipe (walk a run's per-user outputs → local DB via the
   `ingest` CLI) (D1).
1. ACA Job + ingest CLI: drop global `--user-email` assumption; **retire
   `db/schema.sql` and close #173** — delete the file, `ensure_schema()`, the
   `--schema-path`/`--apply-schema` args, the ACA Job flags, and the Dockerfile
   COPY (D2).
1. Retire legacy single-user recipes (#212).
1. Docs (`infra/README.md`, Justfile help) + an end-to-end dry-run validation
   of pipeline → upload → ACA ingest into a non-prod target.

Standalone backlog (no milestone): move the ACA Job's storage auth from
account-key to managed identity (D3 follow-up).

## 8. Out of scope

- Scrape/classify/score orchestration (Phase 13, done).
- The NUL-byte ingest hardening (separate branch `fix/ingest-strip-nul-bytes`).
- Moving overnight execution itself into the cloud (still local).
