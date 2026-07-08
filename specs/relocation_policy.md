# Relocation policy: wire user preference into per-user scoring gate

**Status:** DRAFT 2026-07-08. Not yet ratified.

## Changelog

_(none yet — draft)_

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

**For now: ship the single-checkbox mapping.** It's correct for the most common
cases (fully remote seekers will have `willing=False` and correctly reject both;
relocation-open seekers will have `willing=True` and correctly accept both). The
Seattle edge case is real but rare enough to defer. If it surfaces as a complaint,
add a second toggle: "open to jobs that require living near an office."
