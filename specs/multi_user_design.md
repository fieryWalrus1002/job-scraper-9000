# Multi-user design

Status: **ratified direction, v2 — implementation not started**
Date: 2026-06-10 (v2, same day as v1; v1's "shared feed" Phase A was rejected)
Baseline: main @ e03e101 (post infra-hardening; #161 private-endpoint cutover live)

## 1. Ratified product decisions

Settled with the user 2026-06-10; the rest of this doc follows from them.

1. **Multi-user = a few invited friends, each with their own job feed.** No
   shared visibility of job data between users — each user has their own
   search params and candidate profile, so their feeds don't align.
1. **Per-user scoring from day one.** The pipeline runs locally on the
   user's (admin's) workstation, manually, overnight, once per friend with
   that friend's `search.yml` + `candidate_profile.yml`. Scored JSONL is
   uploaded to blob storage manually; the ingest job loads it into Postgres.
   The pipeline does not move to the cloud in this phase.
1. **Search params and candidate profiles move into the DB later**, edited
   via a frontend settings form; the admin pulls them down to run the
   pipeline. Interim: hand-maintained YAML per user.
1. **Starter set:** each new user gets ~3–5 example jobs in their feed so
   the UI isn't empty, plus the existing Add Job button for manual entries.
1. **Identity:** Entra `oid` as the stable external key (not email — email
   rotates). Multi-provider (GitHub) is anticipated, Entra-only at launch.
1. **Access stays invite-only** via the `config/auth.yml` allowlist (secret
   volume, manually maintained). Admin UI / Entra groups are future options.
1. **#153 (Alembic startup race) is a prerequisite PR** before the
   multi-user migration ships.

## 2. Core schema move: split postings from scores

Today `raw.scored_job_postings` (PK `dedup_hash`) holds descriptive posting
fields *and* skills-fit scores against one specific profile. With per-user
scoring that denormalization breaks: two friends' searches **will** overlap
on the same posting (same `dedup_hash`, different scores).

Design: **shared storage, per-user visibility.**

- `raw.job_postings` — descriptive fields only, PK `dedup_hash`. One row per
  posting regardless of how many users' runs surfaced it.
- `raw.job_scores` — per-user scoring, PK `(user_id, dedup_hash)`. A posting
  appears in a user's feed **iff a score row exists for them**, which is
  exactly "only the jobs scraped for me."

Why shared posting storage rather than fully per-user rows: no duplicated
description text on overlap, and it matches the pipeline's own structure —
the remote_filter `AnalysisCache` is keyed `dedup_hash | prompt_hash | model`
(profile-independent), so friend B's overnight run reuses friend A's LLM
analyses on overlapping jobs. The privacy requirement is about visibility,
not storage; visibility is enforced by the scores join.

`user_id` stands in for `profile_id` for now (one profile per user). When
profiles become DB entities (§7), scores can re-key to `profile_id` if a
user ever needs multiple profiles; nothing in this phase assumes otherwise.

### DDL sketch

```sql
CREATE TABLE app.users (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id       TEXT,                            -- Entra oid / GitHub username; NULL until first login
    identity_provider TEXT,                            -- 'aad' | 'github' (SWA provider names)
    email             TEXT        NOT NULL UNIQUE,     -- lowercased; allowlist + JIT-link key
    display_name      TEXT,
    role              TEXT        NOT NULL DEFAULT 'member'
                                  CHECK (role IN ('admin', 'member')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at     TIMESTAMPTZ,
    UNIQUE (identity_provider, external_id)
);

-- raw.job_postings: dedup_hash PK + the descriptive subset of today's
-- columns (source, source_job_id, source_url, title, company, location,
-- posted_at, description, scraped_at, salary_*, remote_classification,
-- pipeline_metadata, metadata, ingested_at) plus:
--   created_by UUID NULL REFERENCES app.users(id)   -- manual entries; NULL = pipeline

-- raw.job_scores: per-user scoring + run provenance
CREATE TABLE raw.job_scores (
    user_id         UUID        NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    dedup_hash      TEXT        NOT NULL REFERENCES raw.job_postings(dedup_hash),
    fit_score       SMALLINT    CHECK (fit_score BETWEEN 1 AND 5),
    confidence      raw.fit_confidence,
    score_rationale TEXT,
    ai_fit_detail   JSONB,
    run_id          TEXT        NOT NULL,
    scored_at       TIMESTAMPTZ NOT NULL,
    model           TEXT        NOT NULL,
    provider        TEXT        NOT NULL,
    profile_version TEXT        NOT NULL,
    failure_reason  TEXT,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, dedup_hash)
);
CREATE INDEX ... ON raw.job_scores (user_id, fit_score);
CREATE INDEX ... ON raw.job_scores (user_id, scored_at DESC);
```

Open detail settled here: **score re-runs are last-write-wins.** Ingest
upserts `raw.job_scores` with `ON CONFLICT (user_id, dedup_hash) DO UPDATE`
(today's `DO NOTHING` keeps stale scores forever once profiles evolve).
Posting upsert stays `DO NOTHING` — descriptive fields from the first scrape
win; re-scrape freshness is out of scope.

Note `remote_classification` stays on the posting: it classifies the job
itself, not fit against a profile, and the remote_filter analysis is already
shared across users via the cache.

### Per-user tables

- `app.user_applications` — add `user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE`; PK `(dedup_hash)` → `(user_id, dedup_hash)`; index `(user_id, status)`.
- `app.eval_corrections` — re-key to PK `(user_id, dedup_hash)`. With
  per-user scores, a user correcting *their own* score is legitimate gold
  data for *their* profile — no inter-rater problem, because the rating
  targets differ. (v1's "global + admin-only" rationale died with the shared
  feed.) Snapshot columns (`original_score`, `original_model`,
  `profile_version`) now snapshot from `raw.job_scores` for that user.

## 3. Identity and provisioning

- **PK is an internal UUID, never the provider id.** `external_id` is Entra
  `oid` at launch. `oid` is an Entra-specific claim — it does not exist for
  GitHub/Google — so uniqueness is on `(identity_provider, external_id)` and
  the schema is multi-provider-ready without being multi-provider.
- **Verification step before implementation:** current code reads only
  `userDetails`/`userRoles` from `X-MS-CLIENT-PRINCIPAL` but preserves
  `raw_claims`. Log the claim **keys** (not values) from one live request to
  confirm `oid` (or a `claims` array) is forwarded by SWA to the linked
  backend. Fail fast if no stable id is present — never fall back to email
  as the join key.
- **Providers:** Entra-only at launch. GitHub is preconfigured on SWA free
  tier and is the likely second provider — caveat: SWA `userDetails` for
  GitHub is the GitHub *username*, not an email, so the allowlist becomes
  per-provider when that lands. Google requires SWA Standard plan (custom
  OIDC); skip. SWA built-in invitations exist as an alternative gate
  (free tier caps invited users at 25) but would duplicate auth.yml; revisit
  only if allowlist maintenance gets annoying.

`config/auth.yml` (secret volume, never committed) gains structure:

```yaml
users:
  - email: owner@example.com
    role: admin
  - email: friend@example.com
    role: member
    # provider: github / handle: ... — only when GitHub lands
```

Lifecycle:

1. **Startup sync** (lifespan, after migrations): upsert `app.users` by
   email. Fail fast on malformed YAML.
1. **First login (JIT link):** no user matches `(identity_provider, external_id)` → match by lowercased email → fill `external_id` +
   `identity_provider` + `last_login_at` → **seed the starter set** (§5).
   Subsequent logins match by external id, so a later email rotation in
   Entra doesn't lock the account.
1. **Revocation:** remove from auth.yml → 403 at the gate. Rows remain
   (soft offboard); hard delete = delete the user row, CASCADE takes triage
   state and scores (postings remain — they're shared).
1. Authenticated-but-unprovisioned → 403 with a logged error, never silent.

## 4. API changes

New `CurrentUser` dependency (resolves `Principal` → `app.users` row, 403 if
unprovisioned; one indexed query per request — no cache until latency says
otherwise). Postgres RLS considered and rejected for now: single DB role +
shared async pool would mean `SET LOCAL` ceremony and duplicate policy
maintenance; app-level `WHERE user_id` with composite PKs is proportionate.
Revisit as hardening if the user count ever grows past friends.

- `GET /jobs`, `GET /jobs/{hash}`: `raw.job_postings JOIN raw.job_scores USING (dedup_hash) WHERE job_scores.user_id = %(user_id)s`. The join also
  enforces visibility on the detail route (404 for jobs outside your feed).
- `/applications` CRUD: all queries scoped `user_id = current_user.id`.
- `POST /jobs` (manual entry, **members allowed** — ratified): behavior
  change — if the posting already exists (another user added or scraped it),
  do **not** 409; no-op the posting insert and create *this* user's
  application row (and a stub `raw.job_scores` row so it appears in their
  feed — `model/provider/profile_version = 'user'`, as the current manual
  path does). 409 only if *this user* already has it. Set `created_by`.
- `/eval/corrections`: scoped to own rows for everyone; drop the
  admin-only idea. Corrections snapshot from the user's own score row.
- `GET /me` (new): email, display_name, role — lets the frontend show
  role-appropriate affordances instead of discovering 403s.
- Role gating in this phase is minimal: `admin` exists for future surfaces
  (allowlist UI, cross-user ops); no member-visible difference yet.

## 5. Starter set (onboarding)

3–5 hand-picked example postings inserted once by migration/seed script into
`raw.job_postings` with `run_id`-style marker `example-set` in their score
rows. On a user's first login (JIT provisioning), insert `raw.job_scores`
rows pointing at the example postings (`run_id = 'example-set'`,
`model/provider = 'example'`). Properties that fall out for free:

- Visible only to users who've been seeded (visibility = score row).
- Bulk-removable per user (`DELETE FROM raw.job_scores WHERE user_id = X AND run_id = 'example-set'`) and excludable from any real stats.
- Content: neutral, public, non-personal job ads — pick at implementation.

## 6. Pipeline and ingest changes

The pipeline itself (scrape → prefilter → remote_filter → skills_fit) is
untouched — it already runs against one `search.yml` + one
`candidate_profile.yml`. What changes is around it:

- **Per-user runs:** admin runs the pipeline once per user overnight with
  that user's config files. Local run artifacts should carry the user tag in
  the run dir / `run_id` convention.
- **Ingest must carry the user.** Every uploaded batch is tagged with the
  target user (CLI flag `--user-email` resolved against `app.users`, or an
  embedded field in the JSONL metadata — implementer's choice, but it must
  be explicit). **Fail fast and loudly on a missing or unknown user** — per
  CLAUDE.md, a silent default-to-admin here would be lethal.
- **Ingest writes two tables now:** upsert posting (`DO NOTHING`), upsert
  score (`DO UPDATE`, last-write-wins per §2).
- `scripts/backfill_salary.py` and `scripts/export_eval_corrections.py`
  reference the old table — update in the same PR as the split. All
  `scored_job_postings` consumers are in-repo (api routes, ingest, these two
  scripts), so no compatibility view is needed **provided the local pipeline
  checkout is updated before the next overnight run** (the workstation and
  the deployed API can skew — see deploy ordering, §8).

## 7. Configs-in-DB (next phase after this one, sketched only)

- `app.user_search_configs` and `app.candidate_profiles` — YAML payload (or
  structured columns) + `updated_at`, edited via a frontend settings form.
- **Profile versioning must become automatic** once non-admins edit
  profiles: `profile_version` = content hash, computed on save. The current
  hand-bumped version string is a convention that doesn't survive a UI.
  The scores/eval tables already record `profile_version` as opaque text, so
  nothing breaks.
- Interim bridge: a `pull_user_configs` script materializes a user's
  DB-stored config to the YAML files the pipeline already consumes. The
  pipeline never learns about the DB.
- Data custodianship note: friends' profiles and search activity are
  personal data living in the admin's DB. Current posture (private endpoint,
  single firewall rule) is adequate; keep profile content out of logs and
  out of this public repo.

## 8. Migration & deploy plan

**Prerequisite PR: #153** — wrap the lifespan `alembic upgrade` in
`pg_advisory_lock`. This migration includes a table split + data backfill;
racing it across ACA replicas during a rolling deploy is exactly #153.

Migration `0006_users_and_posting_score_split` (one transaction):

1. Create `app.users`. Seed the bootstrap admin — the migration runs in the
   API container where `config/auth.yml` is mounted; read the admin email
   from it (`BOOTSTRAP_ADMIN_EMAIL` env override for odd cases; **fail fast**
   if neither yields an email — never seed a placeholder).
1. Create `raw.job_postings` and `raw.job_scores`; copy descriptive columns
   into postings, score/provenance columns into scores with
   `user_id = bootstrap admin`; drop `raw.scored_job_postings`.
1. `app.user_applications`: add `user_id`, backfill to admin, `SET NOT NULL`, swap PK to `(user_id, dedup_hash)`, re-index `(user_id, status)`.
1. `app.eval_corrections`: same dance, PK `(user_id, dedup_hash)`.
1. Add `created_by` to `raw.job_postings` (nullable, no backfill).
1. Insert the example postings (or do this in a separate seed step — but
   in-migration keeps it atomic and idempotent via `ON CONFLICT`).

Note `db/schema.sql` (the idempotent raw DDL used by local ingest) must be
rewritten to the new two-table shape in the same PR, and downgrade is lossy
once a second user has rows — acceptable in the window before anyone is
invited.

Deploy ordering for the cutover release:

1. User updates the `auth.yml` secret volume to the `users:` format (manual,
   as all secret changes are).
1. Merge/deploy: lifespan runs advisory-locked migration → startup user
   sync → serve.
1. **Update the workstation checkout before the next overnight pipeline
   run** — old ingest code writes to a table that no longer exists (which
   will fail loudly, which is correct, but plan for it).
1. Verify: `/api/health` 200; admin login sees existing jobs +
   applications; a member login sees only the starter set; member Add Job
   works; eval correction on own score works.

## 9. PR slicing

1. `fix: advisory lock around startup migrations` (#153)
1. `feat(db,api): app.users, JIT provisioning, CurrentUser, /me`
   (auth.yml format, startup sync; no table split yet — users table only)
1. `feat(db,api): split postings/scores, scope all queries per-user`
   (migration 0006 steps 2–6, API query rewrite, ingest two-table writes,
   script updates, schema.sql rewrite)
1. `feat(api): starter-set seeding on first login + manual-entry conflict behavior` (+ frontend role/empty-state tweaks; user runs the dev server)
1. Later phase: configs-in-DB + settings form (§7), GitHub provider when a
   specific friend needs it.

PRs 2 and 3 could merge, but the split keeps each reviewable; nothing
touches `infra/`. Each lands green before the next starts.

## 10. Decision log

| Decision          | Choice                                                                   | Rejected alternative                                                                      |
| ----------------- | ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| Feed model        | Per-user feeds, shared posting storage, visibility via score rows        | Shared scored feed (v1 §2-A); fully per-user posting rows (duplication, fights the cache) |
| Identity key      | Internal UUID PK + `(identity_provider, external_id)`, Entra `oid` first | email (rotates); oid-as-PK (Entra-only, provider-controlled)                              |
| Providers         | Entra now, GitHub when needed                                            | Google (needs SWA Standard); SWA invitations (duplicates auth.yml)                        |
| Access gate       | auth.yml allowlist, manually maintained                                  | Admin UI / Entra groups (future)                                                          |
| Row-level access  | App-level WHERE via CurrentUser                                          | Postgres RLS (ceremony > benefit at this scale)                                           |
| Eval corrections  | Per-user, own scores                                                     | Global admin-only (only made sense for a shared feed)                                     |
| Score re-runs     | Last-write-wins upsert                                                   | Keep-first (`DO NOTHING` — strands stale scores)                                          |
| Manual entry      | Members allowed; shared posting, own application + stub score row        | Admin-only; 409 on cross-user duplicates                                                  |
| Pipeline location | Stays local, manual per-user overnight runs                              | Cloud scheduling (out of scope this phase)                                                |
