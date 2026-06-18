# User configs in DB + settings form (Phase 12)

Status: **ratified; Phase 12 shipped. Phase 18 extends the same settings surface.**
Date: 2026-06-11 (proposed and ratified same day)
Last updated: 2026-06-18 (Phase 18 Settings & Account follow-ups)
Baseline: main @ f5c2e31 (Phase 11 multi-user live; #177 warm-replica fix deployed)
Milestone: [Phase 12](../../milestones/2) · tracking issue #168. Phase 18 follow-ups live in the GitHub milestone "Phase 18: Settings & Account".
Follows: `specs/multi_user_design.md` §7 (this phase was sketched there)

## Changelog

- **2026-06-18 — Phase 18 Settings & Account updates.** Marked Phase 12 as
  shipped; documented `user_search_configs.pipeline_enabled` from migration
  0011; added the Phase 18 search payload follow-ups (`salary_floor_k`,
  LinkedIn experience codes, per-user travel tolerance); updated settings API,
  policy, frontend layout, and deploy notes for the Phase 18 slices.

## 1. Product decisions (settled in discussion 2026-06-11)

1. **Per-user search params and candidate profiles move into Postgres**,
   edited by each user via a frontend settings form. The hand-maintained
   per-user YAML files (and the emailed intake templates) are replaced.
1. **Exactly one profile + one search config per user — final.** Enforced by
   PK `user_id` on both tables. A user who wants a second persona creates a
   second account (second invited email/Entra identity). Deliberate,
   self-limiting friction; revisit only on demonstrated need.
1. **The DB stores the human-facing format** (what the form edits), not the
   pipeline's scraper params. The transform human-format → pipeline config
   is deterministic code versioned with the pipeline. Today the admin does
   this transform by hand from the intake templates; this phase turns that
   into a script.
1. **The pipeline itself does not change and never learns about the DB.**
   A `pull_user_configs` script materializes DB → the YAML files the
   pipeline already consumes (`search.yml`, `candidate_profile.yml`), per
   user. (Phase 13's queue builder may read the DB directly; that's its
   decision, not this phase's.)
1. **`profile_version` becomes a content hash computed on save.** The
   hand-bumped version string doesn't survive non-admins editing profiles
   in a UI. Scores/eval tables already treat it as opaque text — nothing
   breaks.
1. **Classification-vs-policy split:** LLM stages classify job-intrinsic
   facts once, shared and cached. Per-user *policies* (prefilter rules,
   acceptable remote classifications) are cheap filters that live on the
   user's search config. **Defaults are permissive** — the admin is the
   strict outlier; most users won't care.
1. **Operator config stays as committed YAML.** Provider/model selection,
   app thresholds, prompts: config-as-code in `config/`. Only *user data*
   moves to the DB. `config/auth.yml` stays a secret volume, unchanged.
1. Friends' profiles are personal data in the admin's DB (custodianship
   note from multi_user_design §7 carries over): keep profile content out
   of logs and out of this public repo.

## 2. Schema

Two tables, not one: the profile is a **scoring contract** whose content
hash becomes `profile_version`; editing search params must not bump the
profile hash or score comparability breaks for no reason.

```sql
CREATE TABLE app.candidate_profiles (
    user_id         UUID        PRIMARY KEY
                                REFERENCES app.users(id) ON DELETE CASCADE,
    payload         JSONB       NOT NULL,   -- human-facing profile content
    profile_version TEXT        NOT NULL,   -- content hash, computed on save
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE app.user_search_configs (
    user_id          UUID        PRIMARY KEY
                                 REFERENCES app.users(id) ON DELETE CASCADE,
    payload          JSONB       NOT NULL,   -- search targeting (human format)
    policies         JSONB       NOT NULL DEFAULT '{}',  -- §6; empty = permissive
    pipeline_enabled BOOLEAN     NOT NULL DEFAULT true,  -- Phase 18/account toggle; added in 0011
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**JSONB payloads, not structured columns.** The human format will iterate
rapidly while the form is young; structured columns mean a migration per
field rename. Validation happens at the API boundary (and in the push/pull
scripts) with shared Pydantic models — the DB stores what those models
accept, nothing else. Revisit structured columns if a field ever needs
indexing (none does: these tables have at most one row per user).

**`profile_version` format:** `YYYY-MM-DD.<sha256[:12]>` over the canonical
serialization of `payload` (`json.dumps(..., sort_keys=True, separators=(",", ":"))`). Date prefix for humans, hash for machines.
Computed server-side on every save; never client-supplied.

No backfill migration for Phase 12: tables started empty, seeded by the push script (§4).
Migration `0009_user_config_tables` is just the two `CREATE TABLE`s. Migration
`0011_pipeline_enabled_flag` later added `user_search_configs.pipeline_enabled`
as a pipeline/account switch: an account can exist and log in while opting out of
overnight runs without deleting its search settings.

## 3. The human-facing format

The intake templates (`config/job_search_template*.yml`,
`candidate_profile.yml.template` — currently local-only files friends fill
out by hand) are the **starting schema** for the two payloads. This phase
freezes them into Pydantic models:

- `src/user_config/models.py` — `CandidateProfileInput`,
  `SearchConfigInput`, `UserPolicies`. Single source of truth, imported by
  the API, the scripts, and (Phase 13) the queue builder.
- `src/user_config/transform.py` — human format → the `search.yml` /
  `candidate_profile.yml` shapes the pipeline consumes. This codifies the
  transform the admin currently does by hand. Deterministic; covered by
  golden-file tests (template in → known YAML out).

The committed `config/profile/candidate_profile.yml.example` (deleted in
the working tree) is **not restored**: with configs in the DB and the
template frozen into Pydantic models, committed example YAML is dead
weight. The intake templates themselves get retired from local use once
the form ships (they remain the historical seed of the format).

Phase 18 extends the frozen search payload where real usage exposed lossy
round-trips:

- `scrape_preferences.salary_floor_k` — optional LinkedIn salary-floor filter,
  emitted to pipeline YAML as `global.salary_floor_k`.
- `scrape_preferences.linkedin_experience_codes` — LinkedIn experience-code
  list, emitted to pipeline YAML as `linkedin.experience`.
- A per-user travel tolerance field (implementation location to be chosen in
  the Phase 18 slice; expected to be policy-shaped rather than scrape-shaped),
  derived into `policies.remote.max_travel_days` (§6).

## 4. Scripts (admin CLI — this is where the value ships first)

- `scripts/push_user_config.py --user-email X [--profile F] [--search F]`
  — validate a filled-in template against the Pydantic models, upsert into
  the tables, print the computed `profile_version`. This is how the admin
  onboards the friends' already-filled templates **on day one**, before
  any frontend exists. Fail fast on unknown user or invalid payload.
- `scripts/pull_user_configs.py [--user-email X | --all]` — materialize DB
  → per-user run directory (`runs/<user>/search.yml` +
  `candidate_profile.yml` via the transform), ready for the existing
  pipeline invocation. Prints which `profile_version` each materialized
  profile carries so run metadata is traceable.

Both connect to Postgres directly (workstation reaches the DB via the
`AllowHomeClient` firewall rule; `just connect-az-db` already proves the
path). No API involvement — the API is for users, the scripts are for the
admin.

## 5. API changes

All routes scoped to the current user via `CurrentUser`; no admin
cross-user surface this phase (the admin uses the scripts).

- `GET /api/settings` — both payloads + `profile_version` + `updated_at`s
  (null payloads if not yet configured → frontend shows onboarding state). Phase
  18 extends this response with `pipeline_enabled` so the Account & Activity tab
  can show whether overnight runs are enabled for this user's search config.
- `PUT /api/settings/profile` — validate `CandidateProfileInput`, upsert,
  recompute `profile_version`, return it. 422 with field-level errors on
  invalid payload (the form needs them).
- `PUT /api/settings/search` — validate `SearchConfigInput`, derive
  `UserPolicies`, upsert payload + policies.
- `PUT /api/settings/pipeline-enabled` (Phase 18) — toggle
  `user_search_configs.pipeline_enabled` for the current user. It should fail
  loudly if the user has no search config row rather than silently creating a
  partial settings record.

A changed profile takes effect at the next overnight run that the admin
executes — the form should say so ("your next batch of jobs will use this
profile") to set expectations. No pipeline trigger from the API, ever
(decision 4).

## 6. Policies (the per-user prefilter / remote-filter knobs)

Stored in `user_search_configs.policies`. Known fields at draft time:

```yaml
remote:
  acceptable_classifications: [...]   # default: all currently produced classes
  max_travel_days: null               # Phase 18; null = preserve current fallback/default
prefilter:
  excluded_title_terms: []            # default: []
  # further prefilter knobs surfaced at implementation as they're
  # extracted from the current search.yml-coupled config
```

Semantics: policies **gate which postings proceed to skills_fit** for that
user (the expensive per-user stage) and nothing else. Classification stays
shared and cached exactly as today (`AnalysisCache`, `dedup_hash | prompt_hash | model`). An empty `policies` object means everything passes —
permissive by default, per decision 6. The admin's strict settings are
just his row's values.

Phase 12 only *stored and edited* policies and had `pull_user_configs` emit
them into materialized YAML; the pipeline already applied equivalent settings
from `search.yml` at that time. Phase 13 moved per-user policy gating into the
multi-user scoring flow. Phase 18 adds `max_travel_days` as a per-user policy
knob now that remote-filter travel is numeric-only (`estimated_travel_days_per_year`);
see `specs/remote_filter_simplification.md` §7.

## 7. Frontend settings form

Phase 12 shipped the first settings form: profile + search/policy sections,
driven by the same field structure as the Pydantic models, with server 422
errors rendered inline.

Phase 18 rebuilds `/settings` into a clearer four-section surface:

1. **Profile** — candidate profile editor and read-only `profile_version`.
1. **Search Targeting** — identity/search profile, target titles, locations,
   organizations/domains, keywords, cadence/result limits, salary floor, and
   LinkedIn experience codes.
1. **Filters & Policies** — employment types, work arrangements, excluded terms,
   per-user travel tolerance, and the derived-policy preview.
1. **Account & Activity** — signed-in account context and the
   `pipeline_enabled` toggle. Disabling it stops future overnight runs for the
   user's search config; it does not delete settings or existing jobs.

Onboarding state still applies when payloads are null ("no profile yet — fill
this in and your feed gets real jobs after the next run").

## 8. Migration & deploy plan

Historical Phase 12 plan: low-risk relative to Phase 11 — additive schema, no
data movement:

1. Migration 0009 (two CREATE TABLEs) ships with the scripts PR; applies
   via lifespan as usual.
1. Admin pushes his own current YAML + the friends' filled templates via
   `push_user_config.py`. Verify: `pull_user_configs.py --all` reproduces
   functionally identical YAML to the hand-maintained files (diff them).
1. Next overnight run consumes materialized configs; recorded
   `profile_version` switches from hand-bumped strings to content hashes
   (both opaque text — no consumer cares).
1. API + frontend land after the scripts are proven; users take over
   editing their own settings.

Rollback: tables are additive; the hand-maintained YAML keeps working
until step 4 — the scripts are a parallel path, not a cutover.

Phase 18 remains additive: `pipeline_enabled` already exists from migration
0011; new payload/policy fields are JSONB fields validated by Pydantic and can
be introduced without data migration. The main deploy risk is preserving current
default behavior for users whose stored search payloads do not yet include the
new fields.

## 9. Historical Phase 12 PR slicing

Phase 18 implementation slices are tracked in the GitHub milestone "Phase 18:
Settings & Account"; this section is the original Phase 12 slice list retained
for history.

1. `feat(config): user_config models + transform + golden tests`
   (no DB, no API — the frozen format and the codified hand-transform)
1. `feat(db,scripts): config tables (0009) + push/pull scripts`
   (admin workflow end-to-end; value ships here)
1. `feat(api): GET/PUT settings endpoints + content-hash versioning`
1. `feat(frontend): settings form` (possibly split profile/search; user
   drives the dev server)
1. `chore: retire committed config examples + docs update`
   (resolves the dangling `candidate_profile.yml.example` deletion)

Each lands green before the next starts. Issues filed from this list on
ratification, assigned to milestone "Phase 12".

## 10. Phase 13 sketch (separate spec after this ships)

For orientation only — its own proposal comes later. Queue of scrape jobs
built from the Phase 12 tables (DB-table queue: resumable, observable,
worker can become an ACA job later, but **execution stays local — the
admin's residential IP gets flagged by job boards far less than Azure
egress would**). Worker pool with concurrency partitioned by source (never
parallel against one job board; see #12). Fan-in: consolidate all users'
unclassified postings → one shared remote-classification batch (OpenAI
Batch API, #11/#25) → per-user policy gates → skills_fit batched per user
(prompt-cache / local KV-cache consistency) → blob → per-user ingest.
skills_fit gets its analysis cache (extract the generic base into
`src/utils/analysis_cache.py`; key includes profile hash). Per-user
failure isolation: one user's scrape failure must not kill the overnight
run — fail loud per queue job, end-of-run summary. Verify at that time
whether OpenAI Batch and prompt-caching discounts stack.

## 11. Decision log

| Decision            | Choice                                                        | Rejected alternative                                                                                       |
| ------------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Profiles per user   | Exactly one (PK user_id); second account for a second persona | Multi-profile + score re-key to profile_id (no demonstrated need; large cascade into feed UX)              |
| Stored format       | Human-facing JSONB; transform-at-pull in versioned code       | Pipeline format in DB (lossy for the form); structured columns (migration churn while format iterates)     |
| Versioning          | Content hash computed on save (`date.sha12`)                  | Hand-bumped string (doesn't survive a UI)                                                                  |
| Policy placement    | On `user_search_configs`, permissive defaults                 | On the profile (policies are search-shaped, not skills-shaped); separate table (overkill for one row/user) |
| Admin config access | Direct-DB scripts (push/pull)                                 | Admin API surface (needless auth surface; the firewall path exists and is proven)                          |
| Pipeline coupling   | None — pipeline consumes materialized YAML                    | Pipeline reads DB (Phase 13's call, not forced here)                                                       |
| Validation          | Shared Pydantic models (`src/user_config/`)                   | Separate API/pipeline schemas (drift guaranteed)                                                           |
| Operator config     | Stays committed YAML                                          | Everything-in-DB (config-as-code lost for system settings)                                                 |
