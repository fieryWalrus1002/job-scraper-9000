# Spec — companies embedding bottom-veto (pre-skills_fit prefilter)

> **Status: RATIFIED 2026-07-23.** Design and PR-slicing agreed; the §10 open
> items are shipping gates that become filed issues (audit-first). Derived from
> the spike findings in `notes/companies-prefilter/FINDINGS.md` +
> `FINDINGS_SUPP_AIFIT.md` (local-only scratch). The spike branch
> `feat/companies-embedding-ranker-prototype` and its ranker script do **not**
> graduate — this is a separate, slimmer production build; the spike's pure
> functions are extracted into `src/prefilter/embedding/` as slice 0.

## 1. Problem

Company boards bulk-pull *everything* (~2k reqs/user; SpaceX alone ≈ 1,989).
Every posting hits the expensive per-job LLM (`skills_fit`). On Bob's companies
pull only ~13% are strong fits (`ai_fit ≥ 4`); we pay to score a large junk tail.

## 2. Proven result (spike)

Ranking a companies pull by **title-embedding cosine similarity** to the
candidate reference (local nomic, title-only) and dropping the bottom ~30–40%
before `skills_fit`:

| drop bottom | jobs cut | good jobs lost | dropped-pile purity (`ai_fit ≤ 2`) |
| ----------- | -------- | -------------- | ---------------------------------- |
| 30%         | 597      | 15 (6%)        | 89% junk                           |
| 40%         | 796      | 20 (8%)        | 88% junk                           |

Local nomic ≈ OpenAI `text-embedding-3-large` (no reason to pay). Title-only >
title+description. Frame = **veto the worst, don't pick winners**.

## 3. Scope & non-goals

- **Companies source only.** linkedin/jobspy arrive keyword-targeted (Magnus's
  pool is 45% good) — a veto there just deletes good jobs. Hard-scoped in code,
  not config.
- **Embeddings only.** No token/lexical allowlist (settled dead end).
- **Not a winner-picker.** It only removes the confidently-worst; `skills_fit`
  still judges every survivor.
- **Produce-only fit** — the veto reduces `skills_fit` input volume; it never
  writes scores or `raw.*`.

## 4. Cut mechanism — **percentage (rank-based), not absolute threshold**

This is the load-bearing knob, so it gets its own section.

**Decision: cut the bottom N% of the ranking (rank-space), not "drop similarity
< T" (value-space).**

Rationale:

- **All spike evidence is in percentage space.** Table A is "drop bottom N%";
  we have *zero* calibration data for an absolute cosine threshold.
- **nomic cosine values are not calibrated across references.** With the nomic
  retrieval prefix scheme, similarities cluster in a narrow, compressed band,
  and *where* that band sits shifts with the reference text (different profile →
  different absolute scale) and with the model/prefix scheme. A threshold `T`
  tuned on Bob's reference would **not transfer** to Magnus's reference — you'd
  have to re-HITL a `T` per user. A percentage transfers as-is: "bottom third"
  means the same operation for everyone.
- **We hold the whole pull in hand**, so rank-space is free — no streaming
  constraint that would force a per-item threshold.

Trade-off accepted: a percentage cut is *pool-relative* — it removes a fixed
fraction even if a board is unusually clean (slight over-cut) or unusually
junky (slight under-cut). An absolute threshold would adapt to pool quality, but
only if the similarity scale were stable, which the evidence says it is not.

**Optional guard (deferred, needs the 2nd dataset):** a percentage cut with an
absolute *floor* — never keep a posting below some very-low similarity, and/or
never drop one above some high similarity — would bound the over/under-cut
failure modes. We can only set those guard values once a second companies
dataset shows whether the similarity distribution is stable enough for any
absolute anchor to mean anything. Ship percentage-only first; revisit.

**Per-company vs global percentage:** apply the cut **globally across the user's
whole companies pull**, matching the spike (one reference, one global ranking).
A tiny board (momentus, 12 postings) contributes ~negligibly to the cut count,
so global is safe for the current data. Flagged as a re-check item for the 2nd
dataset — if some future user's board mix makes a global cut wipe one small
board, switch to a per-company floor. Not worth pre-building.

**Default depth:** `0.33` (bottom third) as the shipping default, pending the
Bob HITL calibration (open item; the ~6% good-jobs-lost at 30% are marginal 4s
at the boundary — HITL confirms the depth). Config-overridable.

## 5. Where it hooks

`src/pipeline/worker.py`, in `process_job`, **right after `_apply_title_filter`**,
gated on `job["source"] == "companies"`. The worker is already per-`(user, source)`, so:

- The user is known → load their materialized reference from
  `run_user_dir(runs_dir, run_id, email)` (`candidate_profile.yml` +
  `search.yml`, both written by the planner).
- The source is known → the `companies`-only scope is a one-line guard. Note
  `job["source"]` here is the **queue-task category** (`"companies"`), a clean
  literal — not the granular per-posting `source` (`"greenhouse:relativity"`,
  `"lever:x"`). So the guard is correct as written; only *downstream* code that
  filters the **persisted** posting `source` must match board-provider prefixes
  instead of the literal `"companies"`.
- It runs **pre-consolidation**, so each user's own reference vetoes their own
  companies pull; cross-user dedup still happens later in consolidation.

New helper `_apply_embedding_veto(jobs, *, reference_text, config, cache)` sits
beside `_apply_title_filter`. Order: title blocklist first (free, removes
obvious excluded terms), then embedding veto on survivors.

```
raw scrape → _apply_title_filter → [if source==companies] _apply_embedding_veto → persist
```

The dropped count is logged (fail-loud/log-well): `scraped N, kept M after title filter, kept K after embedding veto (dropped D, depth=0.33)`.

## 6. Reference construction

Reuse the spike's `build_reference_text` shape (target titles + summary + core /
adjacent skills + preferred domains). Titles come from the materialized
`search.yml`; the rest from `candidate_profile.yml`. Extract the builder into a
small shared module so the production hook and the calibration harness (§8) use
byte-identical reference text — divergence there silently invalidates the
calibration.

**Which similarity variant (reference mode) is NOT yet decided.** The
`--reference-mode` bake-off swept six ways to compute the score (`blend`,
`keywords`, `keyword-max`, `keyword-mean`, `skills-max`, plus the guarded
`exemplar` ceiling). The two available datasets **disagree on the winner and only
one is statistically usable**:

- On Bob (423 good jobs) `skills-max`/`keyword-max` cut deepest at the ≤7% budget
  (36%/35%) and sit near the exemplar ceiling; `keywords` was the *worst* (22%).
- On Magnus (24 good jobs) `keywords` was the *deepest* (52%) and `skills-max`
  middling (35%) — but with `good_total = 24` the 7% budget is 1.68 good jobs, so
  every variant loses exactly one and the depth is decided by single-job jitter,
  not signal.

See `notes/companies-prefilter/FINDINGS_SUPP_AIFIT.md` Table D. Variant selection
is therefore **gated on the cohort data audit (§10.2), not just cut depth** — we
do not pick a shipping reference mode from two datasets when only one clears the
density floor and they contradict each other. Until the audit, `blend` (V0)
remains the conservative control; `skills-max` is the leading *candidate*, not a
ratified choice.

## 7. Config surface

Split by what it is:

- **System / infra config** (non-secret YAML, e.g. `config/agent/companies_prefilter.yml`):
  embedding `provider` (`ollama`), `model` (`nomic-embed-text-v1.5`),
  `base_url` (`http://localhost:8080/v1`), `prefix_scheme: nomic`, and the
  default `cut_depth: 0.33`. This is operator-tuned, not a user preference.
- **Per-user policy** (`policies.prefilter`, already exists with
  `excluded_title_terms`): add an optional `embedding_veto_depth` override and
  an `embedding_veto_enabled` bool (default on for companies). Kept minimal —
  most users take the system default; the override exists for the rare
  hand-tuned case.
- **Scope** (`companies`-only): **not** config — hardcoded in the hook.

`.env` stays secrets-only; none of the above are secrets.

## 8. Caching

Port the spike's `CacheIdentity` design into a real module
(`src/utils/embedding_cache.py` or under the new prefilter package), append-only
JSONL at `data/cache/companies_prefilter_embeddings.jsonl`. Key =
`schema_version | provider | endpoint_identity | model | input_sha256`.

Key property that makes this cheap: **title vectors are user- and
run-independent** (the title text hashes the same regardless of who scraped it
or when), so SpaceX's ~2k titles embed once and are reused every run and across
every user who targets SpaceX. Only the **reference** vector is per-profile
(key it by profile_version / profile hash) and there are few of those. Cold
cost is one batch of ~2k title vectors per new board; warm cost ≈ zero.

**Vectors stay local — no pgvector / DB storage** (decision 2026-07-23). Local
cosine over a few thousand vectors is sub-millisecond in RAM; the calibration
denominator (raw pool) never reaches the DB anyway (§10.2), so the DB is the
wrong home for these vectors. pgvector on Azure is trivially enableable
(`azure.extensions += VECTOR`) but declined as unnecessary; revisit only for a
future recurring cross-machine calibration job. If the JSONL cache ever grows
unwieldy to append/scan, switch its on-disk format (`.npy`/parquet) — not its
location.

## 9. Eval / calibration harness (lands with, ideally before, the hook)

The spike's measurement method — rank the pull, drop
bottom N%, score the drop against `skills_fit`'s `ai_fit` ground truth (good
lost %, dropped-pile purity) — is the eval. Productionize it as a small
calibration tool (not the full experiment ranker) that:

1. takes a run's `scrape/companies.jsonl` + `skills_fit/scored.jsonl` + the
   user's reference,
1. reuses the shared reference builder (§6) and embedding cache (§8),
1. emits the bottom-drop curve (the Table A shape) for any dataset.

This is what confirms the cut depth on a **2nd companies dataset** before we
trust the default — and it's the red/green the veto needs to not "improve by
vibes."

## 10. Open items (gates before shipping)

1. **Bob HITL** on the veto band → ratify `cut_depth` (currently defaulting 0.33).

1. **Cohort data audit (now the critical path).** The variant bake-off ran on a
   2nd dataset (Magnus) and the result is that we *cannot* pick a variant from two
   datasets: they disagree and Magnus has only 24 good jobs (below any usable
   density floor — see §6 and `FINDINGS_SUPP_AIFIT.md` Table D). Before committing
   to a cut depth **or a reference mode**, run the read-only audit from
   `notes/companies-prefilter/ADAPTIVE_PER_USER_CALIBRATION.md`. **Decision
   (2026-07-23): the audit — like the veto and all its vectors — is local-only,
   reading run-dir artifacts, not the prod DB.** Per user, walk surviving run
   dirs (`skills_fit/scored.jsonl` + `scrape/companies.jsonl`) to count label
   density (labeled / good / failures / distinct runs / temporal span) and to
   measure raw-to-scored drop-off (selection bias) by joining the raw pool to the
   scored set on `dedup_hash`. The local artifacts are *richer* than the DB
   projection — the DB keeps only the current score per `(user, dedup_hash)` and
   never stores the raw pool at all (ingest pairs posting+score writes from the
   scored JSONL), so it structurally cannot measure selection bias. Vectors stay
   in the local append-only cache — no pgvector/DB storage. A prod-DB density
   cross-check is possible but deferred (that doc's Appendix A), relevant only if
   a recurring cross-machine calibration job is ever pursued.

   Note the **shadow-mode bootstrap constraint**: because the veto sits before
   `skills_fit`, going live stops generating labels for the tail it drops — so
   shadow mode (log hypothetical drops, still score everything) must precede any
   live routing, or the veto poisons its own validation data.

1. **Variant selection** (`--reference-mode`) is gated on that audit, not just cut
   depth. `skills-max` leads on the one usable dataset but is not ratified.

1. Ratify this spec → file it as a phase milestone + PR-sliced issues. First slice
   = the cohort audit (read-only), before any adapter/storage work.

## Changelog

- (draft) initial proposal.
- (draft) Ran the `--reference-mode` bake-off on both Bob and Magnus. Datasets
  disagree on the winning variant and Magnus is below the usable good-job density
  floor, so variant selection is now explicitly gated on the cohort data audit
  (§6, §10.2–§10.3), not just cut depth. `skills-max` recorded as leading
  candidate, not ratified.
- (draft) Grounded the audit against the schema: runtime veto is fully local;
  only the audit reads prod DB (density via SQL). Recorded that the DB cannot
  measure selection bias (posting+score ingested together from scored JSONL), so
  that check is a local run-dir measurement, and added the shadow-mode bootstrap
  constraint (§10.2).
- (draft) **Decision (2026-07-23): fully local — no prod DB, no pgvector.** The
  local run dirs are richer than the DB projection (retain the raw pool + per-run
  label history the DB drops), so the audit reads run-dir artifacts for *both*
  density and selection bias; the prod-DB density read is demoted to an optional
  deferred cross-check. Vectors stay in the local append-only cache (§8);
  pgvector declined as unnecessary (trivially enableable if a recurring
  cross-machine calibration job is ever pursued).
- **Ratified 2026-07-23.** Design + PR-slicing agreed. §5 clarified that the hook
  guards the queue-task category `"companies"` (verified against
  `planner.py:50 _SCRAPER_SOURCE_KEYS`), distinct from the granular persisted
  posting `source` (`greenhouse:…`/`lever:…`). Committed to `main` via a docs
  branch, decoupled from the non-merging spike branch. Milestone + issues to be
  filed next (slice 0 = extract `src/prefilter/embedding/`; slice 1 = local
  audit loaders + CLI).
