# Remote-filter simplification: split classification from travel judgment

**Status:** RATIFIED 2026-06-12. Open questions resolved in §9.

**Related, explicitly deferred:** #97 (remote postings mis-tagged
`location_restricted` because the body merely *mentions* a city, when the
posting plainly says "remote"). That is a classification-quality problem, not a
schema problem. We cannot tune it well until the schema + multi-user pipeline
land and we revisit the eval baseline on real per-user data — so it stays parked
behind this work. This spec deliberately does **not** touch that behavior.

## 1. Problem

`remote_filter` is wrong "a lot" on the travel subcategories. The root cause
is structural, not prompt-tuning: the `remote_classification` enum jams **two
unrelated axes into one field**.

```
remote-ness:  fully_remote · hybrid · onsite_disguised · location_restricted · unclear
travel freq:  remote_with_quarterly_travel · remote_with_monthly_travel · remote_with_frequent_travel
```

The three `remote_with_*_travel` values force the LLM to make a fragile ordinal
call (quarterly vs monthly vs frequent) from prose that rarely states a cadence.
And it is **redundant work**: the model already emits a clean numeric
`estimated_travel_days_per_year`, and `passes_remote_filter` already thresholds
on it:

```python
analysis.estimated_travel_days_per_year > policy["travel"]["max_estimated_days_per_year"]
```

So travel is double-encoded — once as an unreliable bucket the model guesses,
once as a number the model estimates and policy code thresholds. We keep the
number, drop the buckets.

This is *not* an architecture rewrite. The classify-vs-decide split already
exists: `analyze_remote()` (LLM → `RemoteAnalysis`) is separate from
`passes_remote_filter(analysis, config, user_location)` (pure-Python policy
gate). This spec only shrinks **what the LLM is asked to classify** and moves
the travel decision wholly into deterministic policy code.

## 2. Target schema

`RemoteClassification` becomes the remote-ness axis only:

```
fully_remote · hybrid · onsite_disguised · location_restricted · unclear
```

`RemoteAnalysis` is otherwise unchanged. Travel survives entirely as
`estimated_travel_days_per_year: int | None` — already present, already the
better signal. `SCHEMA_VERSION` 2.0.0 → **3.0.0** (MAJOR: enum values removed).
The three dropped values move to `LEGACY_CLASSIFICATIONS` so old eval records
and historical DB rows still parse and render.

## 3. Policy changes

- `config/agent/remote_agent.yml`: delete `travel.prohibited_categories`; keep
  `travel.max_estimated_days_per_year`. Also drop the stale `"onsite"` entry in
  `disallowed_classifications` (not a current enum value — already legacy).
- `passes_remote_filter`: delete the `prohibited_categories` branch. The numeric
  travel-days threshold is the sole travel gate. Verdict for "frequent travel"
  postings is preserved because frequent travel implies days > 15.

## 4. Blast radius

The `RemoteClassification` Literal is duplicated in four places, deliberately
kept in sync (see the comment in `user_config/models.py`), plus the Postgres
enum and the frontend.

| Location                                           | Change                                                                                                         |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `src/agents/remote_filter/models.py`               | Shrink enum; SCHEMA_VERSION→3.0.0; dropped values → LEGACY_CLASSIFICATIONS                                     |
| `src/agents/remote_filter/utils.py`                | Drop `prohibited_categories` branch in `passes_remote_filter`                                                  |
| `prompts/remote_agent/system_prompt.txt`           | Rewrite: 5 buckets + estimate travel days; no cadence buckets. prompt_hash changes → cache cleanly invalidates |
| `config/agent/remote_agent.yml`                    | Remove `travel.prohibited_categories` + stale `"onsite"`                                                       |
| `src/user_config/models.py` + `transform.py`       | Drop travel values from `RemoteClassification` + `derive_policies` acceptable-set                              |
| `src/agents/skills_fit/models.py`                  | Echoes `remote_classification`; align Literal (keep legacy for stored rows)                                    |
| `src/api/routes/jobs.py`                           | Query-filter Literal; keep travel values **accepted for filtering historical rows**                            |
| `frontend/src/lib/filters.ts`                      | Travel filter options become legacy-only (render historical, not offered for new data)                         |
| `db/schema.sql` + `raw.remote_classification` enum | **Left as a superset** — see §5                                                                                |
| `tests/**` (8 files reference the values)          | Update fixtures/expectations                                                                                   |
| `data/eval/ground_truth.jsonl`                     | 3 records carry travel values in `_human_policy` (reasoning only) — see §6                                     |

## 5. DB enum: leave it a superset

Postgres can't cleanly drop ENUM values, and historical `raw.job_postings` rows
may hold them. Decision: **stop producing the travel values but keep them in the
`raw.remote_classification` type.** The enum becomes a documented superset of
what the LLM now emits. No migration, no data backfill. The API filter and
frontend keep them *displayable* so old rows render; they just never appear in
new data. A future narrowing migration is possible but explicitly out of scope.

## 6. Eval impact (eval-forward)

Favorable. The gold set (`data/eval/ground_truth.jsonl`, 106 records) scores on
`_human_verdict` (pass/trash); the travel buckets appear in only **3 records'**
`_human_policy` field, which is human reasoning context, not the scored label.
Expected verdict parity: "frequent travel" postings still trash via the 15-day
threshold.

Eval-forward order for the core slice:

1. Update the prompt + schema.
1. Re-run the baseline scorer against gold — metrics harness must stay green.
1. Re-run the LLM agent against gold; confirm pass/trash metrics hold (no
   regression vs the pre-change run on `data/eval/runs.jsonl`).
1. Only ratify the prompt if metrics are non-inferior.

SCHEMA_VERSION 3.0.0 structurally flags pre-change eval records, which is
correct — they were produced under a different output contract.

## 7. Open question: per-user travel tolerance

Today `max_estimated_days_per_year: 15` is **global** in `remote_agent.yml`.
Once travel is purely numeric and the multi-user pipeline applies policy
per-user (Phase 13), travel tolerance is naturally a **per-user** preference,
like the remote/hybrid/onsite acceptances `derive_policies` already produces.

**Resolved: defer (option a).** Travel tolerance stays global
(`max_estimated_days_per_year`) in this effort. Per-user `max_travel_days` is
tracked as its own backlog issue against the per-user policy schema — it belongs
with the per-user policy surface, not bundled into the bucket removal.

## 8. PR slicing

1. **`feat(remote_filter): collapse travel buckets into numeric threshold`**
   — models.py enum shrink + SCHEMA_VERSION 3.0.0, `passes_remote_filter` drop
   the category branch, prompt rewrite, config edit. Re-run eval, confirm
   verdict parity. The heart of the change; self-contained and eval-gated.
1. **`refactor: align RemoteClassification across user_config / skills_fit / api`**
   — propagate the shrunk enum to the other three Literals; travel values kept
   as legacy/accepted where they describe *stored* data (api filter), dropped
   where they describe *new* intent (`derive_policies`). DB enum untouched (§5).
1. **`chore(frontend): mark travel classification filters legacy`**
   — historical rows still render; not offered for new data. Regenerate
   `schema.gen.ts` if the API filter Literal changed.

Slice 1 ships value alone and is the only one touching the LLM. Slices 2–3 are
mechanical cleanup that can follow.

## 9. Resolved decisions

1. **Per-user travel tolerance** — **deferred** (§7). Separate backlog issue for
   `max_travel_days` on the per-user policy schema.
1. **Prompt rewrite depth** — **minimal** edit: remove the cadence buckets, keep
   the rest, so the eval delta is attributable to the schema change rather than
   prose churn.
1. **`onsite_disguised`** — **kept.** It is on the remote-ness axis for a
   reason and the eval relies on it; not revisited here.
