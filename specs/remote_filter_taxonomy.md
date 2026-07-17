# Remote-filter taxonomy: LLM as extractor, deterministic per-user gate

**Date:** 2026-07-16
**Status:** RATIFIED (2026-07-17). Issues may be derived from the PR-slicing
section.
**Related specs:** `remote_filter_simplification.md` (the travel-bucket collapse
this generalizes), `remote_filter_eval_decoupling.md` (**depends on this** — the
gold label set + categorical metric are built on the taxonomy defined here),
`relocation_policy.md`, `multi_user_design.md`, `configs_in_db_design.md`

______________________________________________________________________

## Objective

Recast the remote-filter LLM as a **pure extractor** and move all
accept/reject judgment into a **deterministic per-user gate** that runs
**before skills_fit**. The LLM answers exactly one categorical question —
*is this job remote, hybrid, onsite, or unclear?* — and extracts supporting
structured fields (geography, timezone, travel, relocation) without deciding
anything with them. A user's location/timezone/travel/relocation preferences
are then applied as a plain deterministic filter over those extracted fields.

This is the same move `remote_filter_simplification.md` made for travel in
SCHEMA_VERSION 3.0.0 (travel stopped being a *classification bucket* and became
a *numeric field policy thresholds*), generalized to the whole taxonomy.

______________________________________________________________________

## Background: why the current taxonomy is wrong

Current 3.0 `RemoteClassification` = `fully_remote | hybrid | onsite_disguised | location_restricted | unclear`. Three concrete defects, all found while scoping
the eval decoupling:

1. **No home for a plainly-onsite job.** The prompt tells the model to output
   `onsite` (`prompts/remote_agent/system_prompt.txt` L22, L32) — a value **not
   in the schema**. Structured outputs constrain generation to the 5 legal
   values, so plainly-onsite jobs get force-bucketed into `onsite_disguised`.
   Observed live: an overnight run classified a wall of RocketLab director/
   technician roles (obviously onsite) as `onsite_disguised`. This is a prompt/
   schema regression and almost certainly a large share of #97 (false on-site
   classifications, the current dominant error).
1. **`onsite_disguised` is overloaded and decision-irrelevant.** It now absorbs
   both "marketed remote but actually onsite" *and* "plainly onsite." For the
   *decision*, both are identical (a remote-seeker drops both). The "was it
   disguised?" signal, if ever wanted, is **derivable** (`onsite` + arrived via
   a remote search context) and does not deserve a top-level class.
1. **`location_restricted` is a modifier riding on the axis.** It means
   "genuinely remote, but geo-gated." The real remote-ness is *remote*; the
   geo-gate already lives in the structured `location_restrictions` field. The
   global policy proves the class is decorative: `passes_remote_filter`
   (utils.py:285/297) gates on the `location_restrictions` and
   `timezone_requirements` **fields**, never on the `location_restricted`
   **class** (the `remote_agent.yml` comment says so outright). The prompt even
   splits the same concept by granularity — "US-based remote" → `fully_remote` +
   `location_restrictions=["US-only"]` (L28) but "remote in [states]" →
   `location_restricted` (L29) — an arbitrary, un-learnable boundary.

Plus the structural gap already documented in `remote_filter_eval_decoupling.md`:
the geo/timezone checks these classes "defer to" exist **only in the advisory
global `passes_remote_filter`** — the operative per-user gate
(`pipeline.scoring._gate_user`) never reads `location_restrictions` or
`timezone_requirements` at all. So in the overnight pipeline that signal is
extracted and then dropped on the floor.

______________________________________________________________________

## Proposed model

### 1. The axis (what the LLM decides)

```
remote | hybrid | onsite | unclear
```

Four mutually-exclusive values, one dimension (remote-ness), nothing else riding
on it. Mapping from 3.0:

| 3.0 value             | → new     | Notes                                                                          |
| --------------------- | --------- | ------------------------------------------------------------------------------ |
| `fully_remote`        | `remote`  | **rename** (decision 1) — "fully" is inaccurate once geo-gated remote folds in |
| `hybrid`              | `hybrid`  | unchanged                                                                      |
| `onsite_disguised`    | `onsite`  | collapse — "disguised" is derivable, not a class                               |
| `location_restricted` | `remote`  | it *is* remote; geo-gate moves to the field                                    |
| `unclear`             | `unclear` | unchanged                                                                      |

`unclear` stays as the honest "no location and no remote policy anywhere"
bucket — not a hedge (prompt L20–22 rule retained).

### 2. Structured extraction (what the LLM emits but never judges)

`RemoteAnalysis` keeps these as **extraction-only** fields — populated, never
used by the LLM to gate:

- `estimated_travel_days_per_year: int | None` — **display-only** (decision 2):
  extracted and shown, never gated on. The estimate is too noisy to reject on;
  the human judges travel from the description.
- `location_restrictions: list[str]` (e.g. `["US-only"]`, `["CA","NY","TX"]`)
- `timezone_requirements: list[str]` (hard requirements only)
- `requires_relocation: bool`
- `requires_local_presence: bool` — **kept as a field** (decision 3). It overlaps
  the axis (an `onsite`/`hybrid` role usually requires presence) but a hybrid
  role can require local presence too, so it stays a distinct extracted flag; it
  powers the location-aware gate (#465). Review for gating redundancy later.

The LLM's contract becomes: *pick the axis value, and extract these fields from
the prose.* No thresholds, no policy, no accept/reject.

### 3. Deterministic per-user gate (where judgment happens) — pre-skills_fit

`pipeline.scoring._gate_user` is the operative gate and runs **before** the
expensive skills_fit call, so a job a user's preferences rule out never costs
skills_fit tokens. It applies **this user's** stored preferences to the
extracted fields, deterministically:

| User preference                         | Gates on (extracted field)                       | Status                                                       |
| --------------------------------------- | ------------------------------------------------ | ------------------------------------------------------------ |
| `acceptable_classifications`            | `remote_classification` (the 4-way axis)         | exists                                                       |
| `acceptable_locations`                  | `location_restrictions` **+** posting `location` | **NEW — move from global policy**                            |
| user timezone                           | `timezone_requirements`                          | **NEW — move from global policy**                            |
| relocation policy                       | `requires_relocation`                            | exists                                                       |
| local-presence + `acceptable_locations` | `requires_local_presence` (#465)                 | exists                                                       |
| ~~`max_travel_days`~~                   | ~~`estimated_travel_days_per_year`~~             | **dropped (decision 2)** — travel is display-only, not gated |

`unclear` is **fail-open (decision 4)**: an `unclear` classification passes
through to skills_fit by default rather than being dropped, so ambiguous jobs
still get scored instead of silently disappearing. (A user can still exclude it
via `acceptable_classifications` if they want; the default is pass-through.)

**The central build:** `_gate_user` gains the location-restriction and timezone
matching that currently lives only in the dead-in-overnight global
`passes_remote_filter`. This simultaneously closes the per-user gap from the
eval-decoupling spec — geo/tz enforcement moves from the advisory global policy
into the real per-user decision, driven by LLM-extracted fields + user prefs.

### 4. Storage: the blob stays a blob (mostly)

Because filtering happens **in-pipeline, before ingest**, the extracted remote
fields are load-bearing *during* the run (the Python gate reads
`_remote_analysis` off the JSONL) but **display-only after ingest**. That is a
*correct* use of jsonb per CLAUDE.md (inert, display-only at consumption) — not
a violation — so they **stay in `pipeline_metadata`**; no column promotion.

- **Column (queryable):** `remote_classification` only — the UI still displays,
  sorts, and filters the axis (`raw.job_postings.remote_classification` ENUM,
  already indexed, already an API filter).
- **Blob (display-only):** travel days, `location_restrictions`,
  `timezone_requirements`, relocation/local-presence flags.
- **Invariant that keeps this honest:** the moment the read-time UI needs to
  filter/sort on any blob field, promote *that* field to a column then (the
  CLAUDE.md rule). Under this model it won't, because that filtering already
  happened pre-skills_fit.

### DB enum migration

`raw.remote_classification` is a Postgres ENUM carrying historical values
(incl. the legacy travel buckets + `location_restricted`). Postgres can add enum
values cheaply but not drop them, and historical rows must still render. So,
mirroring the Phase 14 superset approach:

- `ALTER TYPE raw.remote_classification ADD VALUE 'remote'`, `'onsite'`.
- New writes use only `{remote, hybrid, onsite, unclear}`.
- Old values (`fully_remote`, `onsite_disguised`, `location_restricted`,
  `remote_with_*_travel`) retained as a read-side superset for historical rows;
  API/UI keep them in the filter Literal (as they already do for the legacy
  travel values).

______________________________________________________________________

## Relationship to the eval-decoupling spec

`remote_filter_eval_decoupling.md` **depends on this spec** and should not have
its gold label set finalized until this ratifies:

- The classifier-native categorical metric becomes a clean **4×4** confusion
  (`remote/hybrid/onsite/unclear`) — no fuzzy `onsite` vs `onsite_disguised` or
  `US-only` vs `states` boundaries to smear it.
- The slice-5 gold re-derivation must relabel to the 4-way axis (the ~52 legacy
  `onsite` rows finally have a real home; `location_restricted` rows become
  `remote` + a `location_restrictions` value).
- The `RemoteFilterInput` input contract (that spec's slice 1) is orthogonal and
  still applies unchanged.
- The gate unit tests (that spec's slice 3) expand to cover the new geo/tz
  matching in `_gate_user`.

______________________________________________________________________

## PR-slicing (draft — file issues only after ratification)

1. **Prompt + schema: 4-way axis.** Rewrite the prompt to emit
   `remote/hybrid/onsite/unclear` (fix L22/L32); update the `RemoteClassification`
   Literal; keep old values as a documented superset. Bump `RemoteAnalysis`
   SCHEMA_VERSION (major). Extraction fields unchanged.
1. **DB enum migration** — add `remote`/`onsite`; retain legacy values;
   update API filter Literal + frontend enum (#325 rides along).
1. **`_gate_user` geo/tz build-out** — apply `location_restrictions` vs
   `acceptable_locations` and `timezone_requirements` vs user timezone,
   deterministically, over extracted fields; make `unclear` fail-open
   (decision 4). Table-driven unit tests. Closes the per-user geo/tz gap.
1. **Retire the global policy's role in overnight** — `passes_remote_filter`
   is removed from the overnight path (and the binary eval that scored it is
   dropped, per `remote_filter_eval_decoupling.md` decision). Coordinate with
   `remote_filter_eval_decoupling.md`.
1. **Travel → display-only (decision 2)** — drop the `max_travel_days` gate from
   `_gate_user`; keep `estimated_travel_days_per_year` as an extracted,
   display-only field. Retires the #215 travel gate.
1. **Docs** — update `remote_agent.yml` comments, `remote_filter_simplification.md`
   cross-ref, and this spec's changelog.

______________________________________________________________________

## Resolved decisions (ratified 2026-07-17)

1. **Rename `fully_remote` → `remote`.** Once `location_restricted` folds in,
   "fully" is inaccurate (a US-only remote role isn't remote-anywhere). Do the
   rename now, while already migrating the enum. New enum values `remote` +
   `onsite`; legacy values kept as a read-side superset.
1. **Travel is display-only, not gated.** Drop the `max_travel_days` per-user
   gate. `estimated_travel_days_per_year` is still extracted and displayed, but
   the estimate is too noisy to reject on — the human judges travel from the
   description. Retires the #215 travel gate.
1. **`requires_local_presence` survives as an extracted field.** It overlaps the
   axis but a hybrid role can require local presence too, so it stays distinct;
   it powers the location-aware gate (#465). Review for gating redundancy later.
1. **`unclear` is fail-open.** With no global `on_unclear_classification` policy,
   an `unclear` job passes through to skills_fit by default so ambiguous jobs get
   scored rather than silently dropped. A user may still exclude it via
   `acceptable_classifications`.

______________________________________________________________________

## Changelog

- **2026-07-16 — draft.** Initial proposal. Emerged from the eval-decoupling
  work: probing the label set surfaced that `onsite` has no schema home
  (prompt emits an illegal value; plainly-onsite jobs land in `onsite_disguised`,
  likely driving #97), `onsite_disguised` is decision-irrelevant, and
  `location_restricted` is a field-modifier masquerading as a class. Converged on
  LLM-as-extractor + deterministic pre-skills_fit per-user gate, with geo/tz
  enforcement moved from the advisory global policy into `_gate_user`, and the
  extracted fields staying display-only jsonb post-ingest.
- **2026-07-17 — ratified.** Four open questions decided (self-review): (1)
  rename `fully_remote` → `remote`; (2) travel → display-only, drop the
  `max_travel_days` gate; (3) keep `requires_local_presence` as an extracted
  field; (4) `unclear` is fail-open (passes to skills_fit by default). Status →
  RATIFIED; PR-slicing updated (slice 5 = travel display-only). Issues may now be
  derived.
