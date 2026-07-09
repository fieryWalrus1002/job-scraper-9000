# Relocation policy: wire user preference into per-user scoring gate

**Status:** §§1–6 RATIFIED + shipped (#448 / #449, 2026-07-08). §8 (location-aware
local-presence, issue #465) DRAFT 2026-07-08 — not yet ratified.

## Changelog

- 2026-07-08 — §§1–6 shipped: `RelocationPolicy` + `derive_policies` wiring (#448,
  `adb39c9`); per-user relocation gate in `score_run` + permissive consolidation (#449,
  `f280802`).
- 2026-07-08 — added §8: location-aware `requires_local_presence` gate (issue #465),
  resolving the §7 open question. `willing=False` no longer blunt-drops every
  local-presence job — it keeps jobs whose posting location matches the user's
  acceptable locations. v1 matches the **raw posting `location` string** (no
  `RemoteAnalysis` schema change / re-classification). See §8.

## 1. Problem

The remote_filter agent emits two boolean flags on every job analysis:

- `requires_local_presence` — job is listed remote/hybrid but implicitly requires
  living within commuting distance of an office (e.g. "remote with weekly on-site").
- `requires_relocation` — posting explicitly states or strongly implies the
  candidate must move.

`passes_remote_filter` gates both against a `policy["relocation"]` block:

```python
if not policy["relocation"]["allow_required_relocation"] and analysis.requires_relocation:
    return False, "requires_relocation"

if not policy["relocation"]["allow_local_presence_required"] and analysis.requires_local_presence:
    return False, "requires_local_presence"
```

Both flags default to `False` — and because the check runs in the **global
consolidation phase** using only `config/agent/remote_agent.yml` (hardcoded
`allow_required_relocation: false`, `allow_local_presence_required: false`), every
job carrying either flag is trashed for every user, globally, with no way for a
user to opt in.

The user-facing input already has a "Willing to relocate" checkbox
(`locations.relocation.willing`) that is collected by the frontend, validated by the
API, stored in the DB — and then silently discarded. `derive_policies` never reads
it. The policies written to disk and applied per-user have no relocation block at
all.

Discovered 2026-07-08 when a user open to relocation had a `requires_local_presence`
job trashed; DB/log investigation confirmed the global default was the culprit.

## 2. Design

### 2.1 Move the gates to the per-user scoring phase

The consolidation phase (global) should be maximally permissive: its job is to
build the shared posting pool, not to apply per-user preferences. This is the
same principle behind `acceptable_classifications` and `max_travel_days`, which
are also enforced per-user in `pipeline.scoring.score_run`, not in consolidation.

**Fix:** set both relocation flags to `true` in `config/agent/remote_agent.yml`'s
global `policy_thresholds.relocation` block so consolidation never trashes on
relocation. Add the relocation gate to `score_run` alongside the existing
`acceptable_classifications` and `max_travel_days` per-user gates.

### 2.2 Wire `relocation.willing` into `UserPolicies`

Add a `RelocationPolicy` model to `src/user_config/models.py` and a `relocation`
field to `UserPolicies`. `derive_policies` maps the user's single boolean input
to both gate fields:

```
willing = True  →  allow_required_relocation: true,  allow_local_presence_required: true
willing = False →  allow_required_relocation: false, allow_local_presence_required: false
```

Rationale: a user unwilling to relocate doesn't want jobs that require them to be
near a specific office (that's either relocation or already living there), and a
user open to relocation is fine with both. A single checkbox covers both cases
cleanly. A future refinement could split the two gates if the distinction matters
(see §7).

### 2.3 Apply the gate in `score_run`

`pipeline/scoring.py`'s `score_run` already reads `UserPolicies` per user and
applies `acceptable_classifications` and `max_travel_days` gates before feeding
jobs to skills_fit. Add the relocation gate there:

```python
if not relocation_policy.allow_required_relocation and posting_meta.get("requires_relocation"):
    continue  # drop, log as "requires_relocation"
if not relocation_policy.allow_local_presence_required and posting_meta.get("requires_local_presence"):
    continue  # drop, log as "requires_local_presence"
```

The remote_filter analysis values are already stored in the enriched job records
that flow into scoring (via `_remote_analysis`). No new LLM calls or re-analysis
needed.

### 2.4 Default behavior for existing users

Existing users who have never touched the relocation checkbox have
`willing = False` in their stored search config (the frontend default). This means
the new per-user gate silently trashes the same jobs that the old global gate did —
**no behavior change for them.** Only users who explicitly set `willing = True`
will see new jobs.

This is the correct default: permissive-by-surprise is worse than
consistent-with-prior-behavior.

## 3. Blast radius

| Layer         | File                                             | Change                                                                                                                                 |
| ------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| Models        | `src/user_config/models.py`                      | Add `RelocationPolicy(allow_required_relocation, allow_local_presence_required)`; add `relocation: RelocationPolicy` to `UserPolicies` |
| Transform     | `src/user_config/transform.py`                   | Read `search.locations.relocation.willing` in `derive_policies`; populate `RelocationPolicy`                                           |
| Global config | `config/agent/remote_agent.yml`                  | Flip `allow_required_relocation` and `allow_local_presence_required` to `true` (consolidation becomes permissive)                      |
| Scoring       | `src/pipeline/scoring.py`                        | Add per-user relocation gate in `score_run` after existing classification and travel gates                                             |
| Worker        | `src/pipeline/worker.py`                         | `_load_policies` already validates through `UserPolicies.model_validate`; no change if model defaults are correct                      |
| Tests         | `tests/user_config/test_transform.py`            | Add cases: `willing=True` → both allow flags true; `willing=False` → both false; missing → false                                       |
| Tests         | `tests/pipeline/test_scoring.py` (or equivalent) | Add cases for relocation gate: `willing=False` drops flagged jobs; `willing=True` passes them                                          |
| Frontend      | None                                             | "Willing to relocate" checkbox already exists and is already wired; no change needed                                                   |
| API           | None                                             | `PUT /settings/search` already calls `derive_policies`; fix flows through automatically                                                |

`pipeline/consolidation.py` and `src/agents/remote_filter/utils.py` are **not
changed** — the global check in `passes_remote_filter` is made a no-op by flipping
the config, not by removing code.

## 4. What is NOT in scope

- Splitting `requires_local_presence` and `requires_relocation` into two separate
  user-facing toggles (see §7 — deferred).
- Backfilling scores for jobs that were incorrectly trashed before this fix. Those
  jobs are gone from the per-user scoring pool; a re-run of the pipeline for
  affected users would be needed separately.
- Changing the LLM prompt or `RemoteAnalysis` schema — both flags are already
  correctly emitted.
- Any eval harness changes — these are policy gates, not LLM output changes.

## 5. Migration / existing data

No DB migration needed. `policies` is stored as JSONB; the new `relocation` block
will be added by `derive_policies` on the next settings save. Until a user saves
their settings, their stored policies have no `relocation` key — `UserPolicies`
must default `relocation` to `RelocationPolicy(allow_required_relocation=False, allow_local_presence_required=False)` so `model_validate({})` produces the
restrictive default (matching prior behavior).

## 6. PR slicing

1. **`fix(user_config): derive relocation policy from willing-to-relocate flag`**
   — `RelocationPolicy` model + `UserPolicies.relocation` field + `derive_policies`
   wiring. Unit tests in `test_transform.py`. Self-contained; no pipeline changes.

1. **`fix(pipeline): apply per-user relocation gate in scoring; make consolidation permissive`**
   — flip `remote_agent.yml` global flags to `true`; add relocation gate to
   `score_run`. Tests covering both willing and unwilling cases. Depends on #1 for
   the `RelocationPolicy` type.

Slice 1 is a pure model/transform change with no pipeline behavior change (the
derived policy is written to disk but the scoring gate doesn't exist yet, so
nothing changes in production). Slice 2 delivers the actual behavior fix. Keeping
them separate makes each PR reviewable and individually revertable.

## 7. Open question: split the two toggles?

`requires_local_presence` and `requires_relocation` are meaningfully different:

- `requires_relocation` = you must move. Clearly a relocation decision.
- `requires_local_presence` = job is labeled remote but you must be near an office.
  Whether this is acceptable depends on whether the user already lives near relevant
  offices — not just whether they're willing to move in the abstract.

A user currently in Seattle who doesn't want to relocate might be perfectly happy
with a `requires_local_presence` job if the office is in Seattle. The current
single-checkbox design can't express this nuance.

**Deferred at ship time; resolved by §8** (issue #465 — the Seattle case surfaced as
a real complaint). Rather than a second toggle, §8 makes the local-presence gate
**location-aware**: a `willing=False` user keeps local-presence jobs that are in their
acceptable locations. No new user-facing control.

## 8. Location-aware `requires_local_presence` gate (issue #465)

**Status:** DRAFT — v1 (raw-location matching). Resolves §7.

### 8.1 Problem restated

§2.2 maps `willing=False → allow_local_presence_required=False`, and the §2.3 gate
then drops **every** `requires_local_presence` job for that user. But
`requires_local_presence` means "must be near *an* office" — it is only a rejection
if that office is somewhere the user won't be. For a Seattle user unwilling to
relocate, a Seattle-office local-presence job is *exactly what they asked for*, yet
it is silently trashed. `requires_relocation` (must move) stays a clean veto; only
`requires_local_presence` needs to become location-aware.

### 8.2 Design — new gate semantics

`requires_relocation` is **unchanged**: dropped when `not allow_required_relocation`
(reason `requires_relocation`).

`requires_local_presence` gets a three-way decision:

```
if requires_local_presence:
    if allow_local_presence_required:          # willing=True → accept near any office
        keep                                    # (UNCHANGED behavior for willing users)
    elif _location_matches(posting.location, relocation.acceptable_locations):
        keep                                    # local to a place they accept
    elif not posting.location:                  # posting has no usable location
        drop, reason "local_presence_ambiguous_location"
    else:
        drop, reason "local_presence_out_of_area"
```

- **`willing=True` path is byte-for-byte unchanged** (`allow_local_presence_required`
  is already `True` for them → accept near any office; they'd relocate anyway).
- **`willing=False` path** changes from "always drop" to "keep iff the posting's
  location matches an acceptable location." Ambiguous/missing location ⇒ conservative
  drop, with a distinct log reason so the two drop causes are separable (acceptance
  criterion).

### 8.3 Config boundary — `acceptable_locations` in the stored policy

`score_run` reads only the stored `UserPolicies` (the `sc.policies` JSONB), **not**
the raw search config — so the acceptable locations must be promoted into the policy.
Per the repo's data-boundary rule (a field that is now branched on is load-bearing →
validated Pydantic field), add:

```python
class RelocationPolicy(_Strict):
    allow_required_relocation: bool = False
    allow_local_presence_required: bool = False
    acceptable_locations: list[Location] = Field(default_factory=list)  # NEW
```

`derive_policies` populates it by de-duplicating `user.home_location` +
`locations.acceptable` into `Location(city, region, country)` entries. It does **not**
depend on `willing` — the list is the user's geography, consulted only on the
`willing=False` branch.

### 8.4 Matching rule (v1)

`_location_matches(job_location: str | None, acceptable: list[Location]) -> bool`,
in `pipeline/scoring.py`:

- Empty/whitespace/`None` `job_location` ⇒ `False` (the gate treats "no acceptable
  match AND no usable location" as the *ambiguous* reason via a separate emptiness
  check).
- Casefold the posting location and split it into alphanumeric **tokens** (so
  `"Seattle, WA"` → `{"seattle", "wa"}`). A `Location` matches when its **city**
  (casefolded) appears as a substring of the posting string **and** its **region**
  (casefolded) appears as an **exact token**. The exact-token region guard is what
  keeps `Portland, OR` from matching `Portland, ME` (and stops the 2-letter code from
  matching as an incidental substring, e.g. `"or"` inside `"portland"`). Country is
  not required to appear.
- Any single acceptable `Location` matching ⇒ `True`.

This is deliberately simple string matching over the scraped `location` field
(`"Seattle, WA"`, `"Seattle, WA, US"`, `"Remote - Seattle, WA"`).

**Documented v1 limitation:** region is matched by exact form, so a config storing the
full state name (`"Washington"`) will **not** match a posting abbreviated `"WA"` (and
vice-versa). Postings from the scrapers use 2-letter codes almost universally, so the
practical guidance is that stored regions should be 2-letter codes. Full-name↔abbrev
equivalence (a small state table, or normalizing at config-save time) is deferred to a
follow-up — as is any structured LLM-extracted required-location (see §8.6).

### 8.5 Migration / existing data

No DB migration. Existing stored policies have no `acceptable_locations` key →
`model_validate` defaults it to `[]` → a `willing=False` user with an un-re-derived
policy still drops every local-presence job (**exactly today's behavior**) until
their next settings save repopulates the list. Safe, no permissive-by-surprise.

**Operational note (post-deploy):** because the list is only written by
`derive_policies` on a settings save, **the fix does not reach an existing user until
their search config is re-saved/pushed** (which re-runs `derive_policies` and writes
`acceptable_locations` into `sc.policies`). Newly-onboarded users get it immediately.
To activate the fix for existing affected users at deploy time, trigger a re-derive of
their stored policies (a settings re-save, or a one-off backfill that re-runs
`derive_policies` over stored search configs).

### 8.6 Not in scope (v1)

- Adding a structured `required_location` to `RemoteAnalysis` / changing the
  remote_filter prompt or re-classifying postings. v1 matches the scraped
  `location` string only. If string matching proves too lossy, a follow-up adds the
  LLM-extracted required location.
- Geocoding / commute-radius / metro-area matching. City+region string match only.
- `excluded` locations as a veto. Only `home_location` + `acceptable` feed the match.

### 8.7 PR slicing (v1)

1. **`fix(user_config): carry acceptable locations into relocation policy`** —
   add `RelocationPolicy.acceptable_locations`; populate in `derive_policies`; unit
   tests in `tests/user_config/test_transform.py`. Non-pipeline; no scoring change yet
   (the field is written but not yet consulted). Gate suite: `tests/user_config`.
1. **`fix(pipeline): location-aware local-presence gate in scoring`** — `_location_matches`
   - rewrite the local-presence branch in `score_run` with the three-way decision and
     distinct log reasons; docker tests in `tests/pipeline/test_scoring.py`. Depends on #1
     for the `acceptable_locations` field. Gate suite: `tests/pipeline/test_scoring.py -m docker`.
