# Multi-user pipeline orchestration (Phase 13)

Status: **ratified — implementation not started**
Date: 2026-06-12 (drafted and ratified same day)
Baseline: main @ 86752b4 (Phase 12 complete; settings round-trip verified live)
Milestone: [Phase 13](../../milestones/3) · spec sketched in `configs_in_db_design.md` §10
Follows: `multi_user_design.md`, `configs_in_db_design.md`

## 1. Why this phase exists

Today's overnight script (`scripts/run_overnight.sh`) is single-user: one
`search.yml`, one `candidate_profile.yml`, one straight-line invocation of
scrape → prefilter → remote_filter → skills_fit → ingest. Phase 11 added
several real users with per-user feeds; Phase 12 put their search params
and profiles in the DB. The pipeline still has to actually *run* for all
of them, every night, without:

- the admin maintaining N copies of `search.yml` and rerunning the script
  by hand,
- N independent passes paying the LLM cost for classifying the same
  overlapping postings N times,
- one user's scrape failure silently taking down the whole overnight run,
- or shipping the pipeline to Azure (residential IP keeps the scrapers
  unblocked — Phase 11's settled call still holds).

The reshape is the smallest change that lets the admin type `just run-overnight` once and get correct, per-user scored feeds for everyone
who has settings in the DB, with shared LLM work shared exactly once.

## 2. Ratified product decisions (carried forward)

These come from the prior phases' decision log and the
\[[project-phase12-13-design]\] discussion. Listing them here so the
implementation has one place to point at.

1. **Execution stays local.** Workstation overnight, residential egress.
   The queue worker may become an ACA job *later* (decision deferred).
   Azure-side LLM calls are fine — only scraping needs the residential IP.
1. **Single profile / single search config per user, final.** Enforced by
   PK `user_id` on both Phase 12 tables. Phase 13 reads, does not re-key.
1. **Classification vs policy split.** Job-intrinsic facts (remote class,
   anything else a model decides about *the posting*) are classified once,
   cached, and shared across users. Per-user *policies* (acceptable remote
   classes, prefilter exclusions) are cheap filters applied after.
   Defaults are permissive.
1. **Per-user failure isolation.** One user's scrape failure must not kill
   the overnight run. Fail loud per queue job (project rule: fail fast
   with stack traces) and emit an end-of-run summary.
1. **Scrape concurrency partitioned by source.** Never parallel against a
   single job board — ZipRecruiter is already Cloudflare-blocked (#12)
   and LinkedIn will follow if we push it. Two scrapes for the same source
   serialize even if they belong to different users.
1. **DB-table queue.** Resumable, observable, inspectable from the same
   psql we already use. Worker is a process. Schema below (§5).

## 3. Pipeline shape: fan-out → fan-in → fan-out

```
                      ┌──────────────┐
   per-user × source  │   scrape     │   per (user_id, source) job in the queue
   (concurrency-      │   workers    │   policy: ≤1 in-flight per source globally
   partitioned by     └──────┬───────┘
   source — §6)             │ postings (deduped by dedup_hash)
                            ▼
                    ┌────────────────┐
                    │ per-user       │   each user's policies.prefilter
                    │ prefilter      │   (cheap, in-process; not a queue job)
                    └──────┬─────────┘
                           │ postings that survived prefilter, per user
                           ▼
                    ┌────────────────┐
   fan-in           │ consolidate    │   union of all users' surviving postings,
                    │ + dedupe       │   keyed by dedup_hash; remembers which
                    └──────┬─────────┘   users want each one
                           │ unclassified postings
                           ▼
                    ┌────────────────┐
   shared LLM work  │ remote_filter  │   AnalysisCache hit → free
                    │ (one batch)    │   miss → OpenAI Batch (#11/#25) if size
                    └──────┬─────────┘   warrants, else live calls
                           │ classified postings (per-posting, profile-free)
                           ▼
                    ┌────────────────┐
   per-user gate    │ remote policy  │   each user's policies.remote
                    │ (per user)     │   .acceptable_classifications
                    └──────┬─────────┘
                           │ postings that survived each user's remote policy
                           ▼
                    ┌────────────────┐
   per-user LLM     │ skills_fit     │   per-user batch (KV / prompt cache
                    │ (per user)     │   warmth is per (user, profile_version))
                    └──────┬─────────┘
                           │ scored JSONL per user
                           ▼
                    ┌────────────────┐
                    │ ingest         │   one ingest pass; per-user file routes
                    │ (per user)     │   to that user's job_scores rows
                    └────────────────┘
```

Two fan-outs (per-user scrape, per-user skills_fit) bracket one fan-in
(shared classification). The current pipeline already enforces the
underlying invariants — `AnalysisCache` is keyed
`dedup_hash | prompt_hash | model` (profile-independent), so consolidation
just makes that benefit visible. skills_fit batches *cannot* be merged
across users without breaking the scoring contract: the prompt embeds the
candidate profile, so a cross-user batch has the wrong system prompt for
some rows.

## 4. Why this and not N independent pipelines

N independent passes is the "do nothing" option — call the existing
single-user script in a `for user in users` loop with materialized YAML
from §4 of `configs_in_db_design.md`. It works. It scales like garbage:

- **Cost:** remote_filter is the cheap-but-non-trivial classifier; the
  per-posting prompt+completion bill is real once overlap is significant.
  Two friends searching "remote software engineer" overlap heavily. N
  passes = N × the remote_filter spend. The cache helps *across nights*
  but not *within one night, between users on first encounter* — fan-in
  catches that.
- **Throughput:** N serial scrape passes means ~N × the wall-clock time
  spent inside per-source rate budgets, even though per-source rate is the
  actual binding constraint. Partitioning by source × user (§6) lets two
  users' scrapes against *different* sources run concurrently without
  poking the same job board harder than today.
- **Failure blast radius:** in a `for` loop, an uncaught exception in user
  3's LinkedIn scrape kills users 4–N's whole overnight. The queue
  contains the blast (§7).
- **Observability:** N stderr streams overlaid in one log file is a
  forensics nightmare. Queue jobs are rows; status is a query.

Phase-13-as-a-loop is a real option to reject, not a strawman: it gets us
correctness now and we could ship it in an afternoon. We're paying the
queue + fan-in complexity to fix cost and isolation, which both compound
as users get added.

## 5. Schema: the queue + the consolidation table

New schema `pipe` (pipeline orchestration), separate from `app` (user
data) and `raw` (job postings/scores). Two tables.

### 5.1 `pipe.scrape_jobs` — the queue

```sql
CREATE TABLE pipe.scrape_jobs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          TEXT        NOT NULL,                  -- 'overnight-YYYY-MM-DD'
    user_id         UUID        NOT NULL REFERENCES app.users(id),
    source          TEXT        NOT NULL,                  -- 'linkedin' | 'indeed' | 'sel' | …
    query_payload   JSONB       NOT NULL,                  -- the scraper input for this (user, source)
    status          TEXT        NOT NULL DEFAULT 'pending' -- pending|running|succeeded|failed
                                CHECK (status IN ('pending','running','succeeded','failed')),
    attempts        INT         NOT NULL DEFAULT 0,
    error           TEXT,                                  -- last error (full traceback, fail-loud)
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    posting_count   INT,                                   -- rows produced on success
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, user_id, source)                       -- idempotent enqueue per night
);

CREATE INDEX ON pipe.scrape_jobs (status) WHERE status IN ('pending','running');
CREATE INDEX ON pipe.scrape_jobs (run_id);
```

Lease semantics: workers claim a `pending` row by `UPDATE … SET status='running', started_at=now(), attempts=attempts+1 WHERE id = $1 AND status='pending' RETURNING …` (atomic; losers see 0 rows and pick the next). No advisory locks needed at this scale.

### 5.2 `pipe.consolidated_postings` — fan-in state

```sql
CREATE TABLE pipe.consolidated_postings (
    run_id          TEXT        NOT NULL,
    dedup_hash      TEXT        NOT NULL,
    requested_by    UUID[]      NOT NULL,                  -- users whose feed should get this if it survives
    posting_ref     TEXT,                                  -- path / id pointing at the canonical postings store
    PRIMARY KEY (run_id, dedup_hash)
);
```

After all `scrape_jobs` for a `run_id` finish, the consolidation step
inserts (or upserts) one row per distinct posting, with `requested_by`
holding the users that produced it post-prefilter. `remote_filter`
operates on the set of rows for `run_id` where the classification cache
misses; results land back in `raw.job_postings` /
`AnalysisCache` exactly as today. `skills_fit` then iterates per user
over the consolidation rows where the user is in `requested_by` *and* the
classification passes that user's `policies.remote.acceptable_classifications`.

Why a separate table and not "just join `raw.job_postings`": the join
asks "which users want this posting *for this run*", and that's a run-
scoped question — a user might appear in tonight's run but not last
night's. The dedicated table makes that explicit and lets the run be
resumable across worker restarts without re-deriving the set.

Both tables go in migration `0010_pipeline_queue.sql`. Schema `pipe`
itself created in the same migration.

## 6. Concurrency and rate-limiting

- **Scrape jobs are claimed one-at-a-time per source globally.** The
  claim query filters out rows whose `source` already has a `running`
  sibling. Two `running` rows with `source='linkedin'` is a violation;
  two rows with `source='linkedin'` and `source='indeed'` is fine. This
  matches the existing per-source rate budget — the queue isn't a license
  to scrape faster, it's a license to run *different sources* in parallel.
- **Worker count:** one process, configurable async concurrency
  (default ≤ number of distinct sources). Single-process keeps the
  workstation footprint sane; the residential-IP constraint means we
  can't horizontally scale anyway.
- **remote_filter is one job, not N.** The OpenAI Batch API decision
  (#11/#25) feeds in here: if the unclassified set is large enough that
  Batch is cheaper than live, submit it as Batch and poll; otherwise live
  calls. Threshold lives in code (start at "any night with > K
  unclassified postings"; K calibrated against the Batch pricing curve at
  implementation). **Verify at that time** whether Batch and prompt-
  caching discounts stack — if they don't, the live-vs-batch threshold
  shifts.
- **skills_fit batches per user.** Profile-version-keyed; the prompt
  prefix is identical across postings within a user's batch, so prompt-
  cache hits compound. No cross-user batching.

## 7. Per-user failure isolation

The project rule is "fail fast and loudly with a stack trace" (CLAUDE.md).
At the queue scale that means:

- Each `scrape_jobs` row that raises captures the **full traceback** in
  `error` and is marked `failed`. The worker continues to the next job.
- The consolidation step ignores `failed` scrape jobs — the run proceeds
  for the users whose scrapes succeeded.
- A `failed` skills_fit step for one user does the same: skip that user,
  log the traceback, finish ingest for everyone else.
- **End-of-run summary** (stderr + one final row in a `pipe.runs` mini-
  table if it earns its keep — start with stderr-only) lists every failed
  job per user. The admin reads this every morning.

Retries are off by default this phase. Re-running the queue (idempotent
on `(run_id, user_id, source)`) is the recovery path: failed rows get
re-claimed; succeeded rows are skipped. Add automatic retry only if a
class of transient failures shows up that's worth automating away.

## 8. The orchestrator (entry point)

One new CLI: `job-scraper-9000 overnight --run-date YYYY-MM-DD`. Replaces
`scripts/run_overnight.sh`. Steps:

1. **Plan.** Read all users from `app.users` who have both a profile and
   a search config (Phase 12 tables). For each (user, source) in the
   user's search config, upsert a `pipe.scrape_jobs` row for `run_id = 'overnight-<date>'`. Idempotent: rerunning skips already-`succeeded`
   rows.
1. **Scrape phase.** Spawn the worker loop. Returns when no `pending`
   rows remain. Per-user prefilter runs inline at the end of each scrape
   job, so the queue row stores already-policy-filtered postings.
1. **Consolidate.** Populate `pipe.consolidated_postings` from the
   succeeded scrape jobs.
1. **Classification phase.** Run remote_filter against the union; cache
   misses become a Batch submission or live calls per §6.
1. **Skills_fit phase.** For each user, iterate the user's surviving
   postings; run skills_fit (one batch per user). Per-user failure here
   isolates per §7.
1. **Ingest phase.** Same `ingest` command as today, called per user with
   per-user JSONL; the user-email/user_id route the rows.
1. **Summary.** Stderr summary; exit non-zero iff *all* users failed
   (any partial success exits zero — the admin reads the summary).

The orchestrator is the only thing that knows about the queue. The
existing per-stage CLIs stay; they remain useful for ad-hoc reruns and
keep tests sane.

## 9. skills_fit analysis cache (extract the base)

CLAUDE.md flags this: "When skills_fit ships its own analysis cache,
extract a generic base into `src/utils/analysis_cache.py` rather than
copy-pasting." The current `src/agents/remote_filter/cache.py` is the
template. The base owns:

- append-only JSONL on disk,
- composite key (subclass declares the key tuple),
- read-through hit/miss for a batch.

skills_fit's key includes `profile_version` (Phase 12's content hash) so
that profile edits cache-miss exactly as prompt edits already do for
remote_filter. The `src/agents/remote_filter/cache.py` file stays as a
thin subclass; existing on-disk cache files are not migrated (the path
moves but the JSONL format doesn't change, so a one-line file rename if
we care). Extraction lands as its own PR before the orchestrator does so
the diff stays readable.

## 10. What this phase explicitly does not do

- **No score re-key to `profile_id`.** Per Phase 12: one profile per user;
  scores stay `(user_id, dedup_hash)`. If a user ever needs multiple
  profiles, that's a future phase and a separate spec.
- **No move to Azure.** ACA-job worker is a future option; this phase is
  workstation overnight.
- **No automatic retries.** Re-run the queue on demand.
- **No worker horizontal scale.** One process, async concurrency.
- **No remote_filter / skills_fit prompt changes.** The classification-
  vs-policy split is already how those agents are built — this phase is
  about *applying* the policies in the right place (post-classification,
  per-user gate), not rewriting the agents.

## 11. PR slicing

Each lands green before the next starts. Issues filed from this list on
ratification, assigned to milestone "Phase 13: Multi-user pipeline
orchestration".

1. **`refactor(utils): extract AnalysisCache base into src/utils/analysis_cache.py`**
   — remote_filter cache becomes a subclass; no behavior change; existing
   on-disk cache file kept in place. The pure-refactor warm-up so the
   orchestrator doesn't carry this churn.
1. **`feat(agents/skills_fit): analysis cache keyed by profile_version`**
   — uses the new base; lands its own dedicated cache file under
   `data/cache/`. Eval-harness still green.
1. **`feat(db): pipe schema (0010) — scrape_jobs + consolidated_postings`**
   — migration only; no orchestrator yet. Includes the lease query as a
   tested SQL helper.
1. **`feat(pipeline): worker + scrape phase end-to-end (queue-driven)`**
   — replaces the scrape step of `run_overnight.sh` for *one user* via
   the queue, with per-source serialization and per-user prefilter
   inline. Wired into a hidden `overnight --scrape-only` flag.
1. **`feat(pipeline): consolidation + classification phase`**
   — fan-in table populated; remote_filter consumes it; live calls only
   for now (Batch in a later slice). End-to-end up through classified
   postings.
1. **`feat(pipeline): skills_fit per user + ingest per user`**
   — completes the fan-out tail. `overnight` is now the real entry point;
   `run_overnight.sh` becomes a one-line wrapper or is retired.
1. **`feat(pipeline): per-user failure isolation + end-of-run summary`**
   — exception capture into `pipe.scrape_jobs.error`, stderr summary,
   exit-code semantics per §7.
1. **`feat(remote_filter): OpenAI Batch path (#11/#25)`**
   — threshold-driven; live below threshold, Batch above. Reuses the
   #11/#25 backlog work. Verifies the Batch+prompt-cache discount
   interaction at submission time.
1. **`chore(scripts): retire run_overnight.sh in favor of overnight CLI`**
   — docs update; `just` recipe lands here.

The first two slices (cache base + skills_fit cache) are independent of
the queue and can ship before the spec is fully de-risked.

## 12. Open questions to settle before issues are filed

These are honest uncertainties, not strawmen — flag your call on each:

1. **`pipe.runs` row, yes or no?** A per-run table makes the end-of-run
   summary a `SELECT` instead of stderr-grepping logs. Costs a tiny bit
   of orchestrator wiring. Lean: yes, but `pipe.scrape_jobs` plus a
   `run_id` index might be enough at three users.
1. **Where do per-user `search.yml` / `candidate_profile.yml` artifacts
   live during a run?** Today `pull_user_configs.py` materializes them
   under `runs/<user>/`. The orchestrator can keep doing that
   per-night, or read the DB directly and pass dicts to each stage. Lean:
   keep materializing to `runs/<user>/<run_id>/` because it's the
   debugging artifact the admin will actually want to inspect when a run
   misbehaves.
1. **What happens if a user has a profile but no search config (or vice
   versa)?** Phase 12 lets either be null. Lean: planner skips the user
   with a warning ("magnus@… has profile but no search — skipping"),
   never silently includes them.
1. **Should the queue support source = `manual_jobs`?** Members already
   add jobs by hand via the Add Job button (`POST /jobs`, Phase 11). They
   don't need scraping but they *do* need skills_fit scoring. Lean: feed
   manually-added postings into the consolidation step directly, no
   scrape job needed — they're already-classified-or-not posts that
   should hit the same downstream path.
1. **OpenAI Batch threshold value.** Concrete number deferred to slice
   8; needs current pricing curves. Spec doesn't try to pin it.
1. **Batch API for `skills_fit` too?** §6 only proposes Batch for
   `remote_filter`. `skills_fit` already benefits from per-user prompt-
   cache warmth, but on overnight runs the Batch discount is real money
   on top of that — same reason it's worth it for `remote_filter`. The
   one wrinkle is whether Batch + prompt-caching discounts stack (open
   for both stages). Lean: add a slice 10 — `feat(skills_fit): Batch path` — same threshold-driven shape as slice 8, lands after slice 6
   so the `skills_fit` orchestration is stable first. Flagging here so
   ratification settles whether to roll it into Phase 13 or carry it
   into a Phase 14.

## 13. Decision log (this phase only)

| Decision                   | Choice                                           | Rejected alternative                                                                                   |
| -------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| Pipeline shape             | Fan-out → fan-in → fan-out                       | N independent per-user pipelines (LLM cost compounds; failures cascade)                                |
| Execution location         | Workstation, residential egress                  | ACA worker (residential IP keeps scrapers unblocked; revisit when scrapers Cloudflare-block us anyway) |
| Queue substrate            | Postgres table (`pipe.scrape_jobs`)              | Redis / Celery / SQS (operationally heavier; we already run Postgres)                                  |
| Concurrency partitioning   | One in-flight per `source` globally              | Per (user, source) (would parallelize against one job board — guaranteed to flag)                      |
| Failure handling           | Per-job traceback in `error`; run continues      | Stop-on-first-fail (kills all users' nights for one bug)                                               |
| Retry policy               | None (re-run the queue)                          | Automatic exponential backoff (premature; no failure-mode data yet)                                    |
| skills_fit batching        | Per user, profile-version-keyed                  | Cross-user mega-batch (wrong system prompt for some rows; voids scoring contract)                      |
| remote_filter batching     | Single set across users; Batch above a threshold | Per-user calls (cache helps cross-night, not first-encounter overlap within a night)                   |
| Cache base extraction      | Yes, before orchestrator                         | Inline copy-paste from remote_filter (CLAUDE.md flags this explicitly)                                 |
| Per-user materialized YAML | Keep — under `runs/<user>/<run_id>/`             | Dict-only handoff (loses the debugging artifact admin needs)                                           |
