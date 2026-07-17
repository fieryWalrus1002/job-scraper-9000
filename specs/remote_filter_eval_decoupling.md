# Remote-filter eval decoupling: classifier eval vs. policy gates

**Date:** 2026-07-16
**Status:** RATIFIED (2026-07-17). Issues may be derived from the PR-slicing
section.
**Depends on:** `remote_filter_taxonomy.md` (RATIFIED 2026-07-17) — the gold
label set and the categorical metric are built on the 4-way axis defined there.
**Related specs:** `eval_framework_requirements.md`,
`remote_filter_golden_dataset_requirements.md`, `remote_filter_eval_tuning.md`,
`remote_filter_simplification.md`, `multi_user_design.md`

______________________________________________________________________

## Objective

Make the remote-filter eval measure what actually decides production outcomes.
Today it scores a policy the overnight pipeline no longer acts on, and the gate
that *does* decide per-user outcomes has no coverage at all. Decouple the
**LLM classifier eval** (gold-set, policy-independent) from the **deterministic
policy gates** (unit-tested), so the eval score stays valid under policy tuning
and multi-user.

______________________________________________________________________

## Problem: three decision layers have drifted apart

There are three layers between a scraped posting and a user's inbox. Only one is
an LLM decision; the eval is bound to a different one.

| Layer             | Function                                                                                                                                                                        | LLM? | Used in overnight?                                                                                           | Eval coverage                     |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- | ------------------------------------------------------------------------------------------------------------ | --------------------------------- |
| **Classifier**    | `agents.remote_filter.utils.analyze_remote` → `RemoteAnalysis` (`remote_classification`, `estimated_travel_days_per_year`, `requires_relocation`, `requires_local_presence`, …) | yes  | ✅ the product                                                                                               | indirect only (via global policy) |
| **Global policy** | `passes_remote_filter(analysis, config, "USA")` (`runner.py:251/310`, `batch.py:398`)                                                                                           | no   | ⚠️ runs, but pass/trash split is **advisory** — `scoring._load_classified` reads *both* files and re-decides | **this is what the eval scores**  |
| **Per-user gate** | `pipeline.scoring._gate_user` — `acceptable_classifications` ∋ classification, numeric `max_travel_days`, relocation/local-presence gates                                       | no   | ✅ the real decision                                                                                         | **none**                          |

### Why this is wrong

- `pipeline/consolidation.py` calls `run_remote_filter`, which writes
  `classified_pass.jsonl` / `classified_trash.jsonl` using the **global**
  `policy_thresholds` from `config/agent/remote_agent.yml`. That split is
  documented as *advisory* (consolidation.py:222): `scoring._load_classified`
  unions both files, and `_gate_user` re-decides per user off
  `_remote_analysis.remote_classification`. The runner's `_filter_result` /
  `_filter_reason` fields are **never read** downstream.
- `scripts/run_remote_filter_eval.py:206` scores
  `passes_remote_filter(analysis, config, "USA")` against a human **binary**
  `_human_verdict` (pass/trash). So the reported precision/recall
  (last run: 0.66 / 0.94, n=104) is tied to the global thresholds — a decision
  overnight ignores. Tune `policy_thresholds` and the eval moves while
  production does not.
- The gates are **pure deterministic functions** of an analysis + a policy.
  They carry no LLM nondeterminism, so they do not belong in a gold-set LLM eval
  at all — they belong in unit tests.

### The consequence to name plainly

The eval green-lights a gate production doesn't use, and the gate production does
use is unevaluated. A false-`trash` classification silently removes a good job
*before* skills_fit ever sees it, so skills_fit's `precision_at_k` can't catch
it — classifier **recall** is load-bearing and currently only measured through
the wrong policy.

______________________________________________________________________

## Second drift: the eval doesn't feed the production prompt

Even setting the label problem aside, the eval measures the classifier on a
**different, thinner input** than production — through a parallel, hand-built
code path.

- **Production** builds the classifier input with
  `agents.remote_filter.utils.build_search_context(job, tz)` (utils.py:98),
  which folds in the consolidated **`search_contexts`** (plural) attached by
  `pipeline.consolidation._attach_search_contexts`, then `_build_user_message`
  emits a **"Search provenance"** block — including the load-bearing hint
  *"returned by a remote-only search filter … treat as weak but relevant
  evidence of remote eligibility."* That block can flip a `fully_remote` vs
  `onsite_disguised` call.
- **The eval** (`scripts/run_remote_filter_eval.py:179`) instead hand-builds
  `search_context = {**search_params, user_timezone}`. It never calls
  `build_search_context` and never includes `search_contexts`. So it feeds a
  thinner prompt through a code path that has already diverged from production
  and will keep diverging.
- **The gold corpus predates the field:** **0 / 106** records in
  `data/eval/ground_truth.jsonl` carry `search_contexts` (it is produced by the
  Phase 13 consolidation step, which post-dates the gold capture). So the
  provenance path cannot be exercised at all, even if the eval called
  `build_search_context`.

What still aligns: gold `search_params` carry `keywords`/`workplace`/`job_type`
on ~38 records, and those *are* read by `_build_user_message` — that slice of
context is not lost. The gap is specifically the newer consolidated provenance
(and any field added to `_SEARCH_CONTEXT_PROMPT_FIELDS` after the gold capture).

### Requirement: eval input fidelity

**Preferred mechanism — a Pydantic input contract.** The classifier input is
currently an untyped `dict` assembled ad-hoc from the raw job record and read
via scattered `search_context.get(...)` calls in `_build_user_message`, with a
hand-maintained `_SEARCH_CONTEXT_PROMPT_FIELDS` set standing in for a schema.
This is precisely the "load-bearing field consumed from an unvalidated dict"
anti-pattern CLAUDE.md's data-boundary rule warns against. Formalize it:

```python
class SearchProvenance(BaseModel):   # replaces _SEARCH_CONTEXT_PROMPT_FIELDS
    source: str | None = None
    workplace: str | None = None
    job_type: str | None = None
    source_detail_location: str | None = None

class RemoteFilterInput(BaseModel):  # the classifier's INPUT contract (≠ RemoteAnalysis output)
    SCHEMA_VERSION = "1.0.0"
    description: str
    title: str | None = None
    location: str | None = None
    keywords: str | None = None
    workplace: str | None = None
    job_type: str | None = None
    user_timezone: str | None = None
    search_contexts: list[SearchProvenance] = Field(default_factory=list)
```

- `build_search_context` becomes the single validated boundary "raw job dict →
  `RemoteFilterInput`"; `_build_user_message` and `analyze_remote` consume only
  the model. **Drift-1 then dies by construction** — the eval cannot hand-roll a
  divergent dict; it must build the same typed object.
- **Drift-2 becomes detectable** — the gold set stores the `RemoteFilterInput`
  (or its hash) per record; a future prompt-field addition changes the schema and
  mismatches old gold, surfacing loudly instead of silently (requirement 3).
- It's a *projection* of the posting (the prompt contract), not the whole record,
  and is distinct from the `RemoteAnalysis` output model — keep them separate.

1. **Kill the parallel path.** With the model in place, the eval constructs its
   input via the *same* `build_search_context` → `RemoteFilterInput` path
   production uses — not a hand-rolled dict. (Absent the model, this is a DRY
   discipline; with it, it's enforced by the type.)
1. **Re-derive the gold corpus from post-consolidation records.** The classifier
   is user-independent and `search_contexts` is attached at consolidation, so
   the source of truth for gold inputs is a real run's
   `_consolidated/postings.jsonl`, not the pre-Phase-13 captured set. Options:
   (a) re-scrape/re-consolidate a fresh corpus and re-label, or (b) enrich the
   existing gold records by back-filling `search_contexts` from a matching
   consolidation pass. (a) is cleaner but costs a full relabel; (b) is cheaper
   but only works where the same postings are still resolvable. **Open
   question — see below.**
1. **Snapshot the resolved prompt in the gold/provenance.** To make input drift
   *detectable* next time, store the `prompt_hash` of the resolved user message
   per gold record (or a corpus-level input hash) so a future field addition
   that changes the prompt surfaces as a hash mismatch instead of silent drift.

______________________________________________________________________

## Proposed model: eval the classifier, unit-test the gates

### 1. Classifier eval (LLM, gold-set, policy-independent)

Score `analyze_remote`'s **native output** against ground-truth labels of the
same fields — no policy in the loop:

- **`remote_classification`** — **4-way** confusion matrix over the axis defined
  in `remote_filter_taxonomy.md` (`remote`, `hybrid`, `onsite`, `unclear`). Same
  machinery shape as skills_fit's `confusion_5x5` in `agent_eval/metrics.py`,
  generalized to a labeled categorical confusion (`compute_categorical_metrics`).
  The 4-way axis is a deliberate win for the metric: no fuzzy `onsite` vs
  `onsite_disguised` or `US-only` vs `states` boundaries to smear the matrix.
- **`estimated_travel_days_per_year`** — MAE / banded agreement against a
  numeric gold (new label; see migration). Note this measures **extraction**
  quality only; travel is display-only and never gated (taxonomy decision 2).
- **`requires_relocation`, `requires_local_presence`** — per-flag
  precision/recall/F1. **Deferred (decision below)** — added only if/when a
  relocation/local-presence misclassification bites; the categorical + travel
  metrics cover the dominant error modes.

This score is invariant to `policy_thresholds` and to which user's policy runs
downstream, so it is valid for the multi-user pipeline.

### 2. Gate correctness (deterministic, unit tests — not the eval harness)

A table-driven test suite asserting `(analysis, policy) → keep/drop` for the
operative gate:

- `_gate_user` (per-user) — **new coverage**: classification membership,
  relocation veto, location-aware local-presence (`_location_matches`), and the
  geo/tz matching the taxonomy moves in from the retired global policy; plus
  `unclear` fail-open (taxonomy decision 4). Cases live in `tests/pipeline/`,
  no LLM, no gold set. Travel is **not** gated (taxonomy decision 2 — display-only).
- `passes_remote_filter` (global) — the taxonomy retires this from overnight and
  the binary eval that scored it is dropped (see decision below). Unit-test it
  only if/while the function survives for a standalone path; otherwise it goes
  with the global policy.

This is where the per-user logic finally gets tested, at unit-test cost and
precision rather than as a fuzzy end-to-end metric.

______________________________________________________________________

## Gold-set migration — cheaper than feared

`data/eval/ground_truth.jsonl` (n=106; 74 trash / 32 pass) **already carries a
human classification** in `_human_policy` — it was labeled during the
teacher-first HITL pass. Current distribution:

```
fully_remote 32 | onsite 52 | hybrid 13 | onsite_disguised 3
location_restricted 2 | unclear 1 | remote_with_monthly_travel 1
remote_with_frequent_travel 2
```

So the categorical gold exists; it needs a **remap + ratify** pass to the 4-way
axis of `remote_filter_taxonomy.md`, not from-scratch labeling. The taxonomy
decision makes this dramatically cheaper than first estimated — the ~52 `onsite`
rows that were the ambiguous bulk now map **directly** (there is finally a real
`onsite` bucket), collapsing the earlier "~58 HITL rows" to a handful:

| `_human_policy` (legacy)          | → axis `remote_classification`           | Notes                                         |
| --------------------------------- | ---------------------------------------- | --------------------------------------------- |
| `fully_remote`                    | `remote`                                 | direct (rename; open q1 in taxonomy)          |
| `onsite` (52)                     | `onsite`                                 | **direct now** — the taxonomy adds the bucket |
| `hybrid`                          | `hybrid`                                 | direct                                        |
| `onsite_disguised` (3)            | `onsite`                                 | direct collapse                               |
| `unclear`                         | `unclear`                                | direct                                        |
| `location_restricted` (2)         | `remote` + `location_restrictions` value | field-fill, minor                             |
| `remote_with_monthly_travel` (1)  | `remote` + travel-days                   | field-fill                                    |
| `remote_with_frequent_travel` (2) | `remote` + travel-days                   | field-fill                                    |

- **Cheap part:** ~101/106 map directly to the axis with **zero** classification
  judgment (the `onsite` ambiguity that inflated the old estimate is gone).
- **Field-fill part:** the 2 `location_restricted` + 3 travel rows need a
  structured field value (`location_restrictions` / `estimated_travel_days`),
  sourced from the teacher `response` or a quick look — not a classification call.
- **New labels (optional, phase 2):** `requires_relocation` /
  `requires_local_presence` bools are not in the gold today — add via a second
  HITL pass only if we want flag-level eval (per taxonomy these are
  extraction-only fields gated deterministically, not part of the axis metric).
  The categorical eval works without them.

Gold field additions: `_human_classification` (canonical 4-way axis label),
`_human_travel_days` (int|None), later `_human_requires_relocation` /
`_human_requires_local_presence` (deferred). `_human_verdict` is no longer
scored (the binary eval is dropped) but is retained in the records as historical
provenance — do not delete, just don't rely on it.

______________________________________________________________________

## Metric changes (`src/agent_eval/metrics.py`)

- **Add** `compute_categorical_metrics(preds, golds, labels)` — labeled N×N
  confusion (here 4×4 over the taxonomy axis) + per-class precision/recall/F1 +
  macro/micro accuracy. Generalizes the skills_fit `confusion_5x5` helpers.
- **Add** numeric travel agreement (reuse ordinal MAE). Per-flag binary metrics
  are deferred (see decision) but would reuse `compute_metrics`.
- **Drop the binary remote-filter eval (decision below).** `run_remote_filter_eval.py`
  stops calling `passes_remote_filter` and stops scoring the pass/trash
  `_human_verdict`; the categorical classifier metric is the only remote-filter
  number. `compute_metrics` itself stays in `metrics.py` as a generic helper
  (still used elsewhere / for deferred flag metrics), it just no longer scores
  remote-filter.
- `run_remote_filter_eval.py` compares `analysis.remote_classification`
  (+ travel) to the new gold fields.

______________________________________________________________________

## PR-slicing (draft — file issues only after ratification)

1. **`RemoteFilterInput` / `SearchProvenance` Pydantic contract** — introduce the
   input model; route `build_search_context` + `_build_user_message` +
   `analyze_remote` through it; delete `_SEARCH_CONTEXT_PROMPT_FIELDS`. Prompt
   output byte-identical for existing inputs (golden-string test). No behavior
   change — pure formalization. **Foundation for the eval-fidelity slices.**

1. **Metrics: `compute_categorical_metrics` + tests** — pure, no data change.

1. **Gate unit tests** — cover `_gate_user` and `passes_remote_filter`
   deterministically (`tests/pipeline/`). Independently valuable; can land first
   (no dependency on the model or gold work).

1. **Eval input fidelity** — rewire `run_remote_filter_eval.py` to build a
   `RemoteFilterInput` via `build_search_context` (kills the parallel path); add
   per-record resolved-prompt hash to the provenance so future input drift is
   detectable.

1. **Gold corpus re-derivation (hybrid)** — resolve the input-drift data gap.
   **Recommended hybrid** (see open question 5): *keep* the 106 human
   classification decisions (`_human_policy` / `_human_verdict` — judgments about
   the job, largely input-independent), but *regenerate* the input-sensitive
   structured fields against today's pipeline:

   - Rebuild each record's classifier input via slice-1 `build_search_context` →
     `RemoteFilterInput`, sourcing real `search_contexts` from a matching
     `_consolidated/postings.jsonl` where postings still resolve; fall back to
     synthesized *self*-provenance (project the record's own `search_params` into
     one `SearchProvenance`) where they do not. **Cross-duplicate provenance is
     unrecoverable for records without a live duplicate set — accept that gap or
     re-scrape those rows.**
   - Remap `_human_policy` → `_human_classification` (4-way axis; ~101/106 map
     directly, only the 2 `location_restricted` + 3 travel rows need a
     structured field-fill — see the migration table above).
   - Re-*propose* `estimated_travel_days_per_year`, `requires_relocation`,
     `requires_local_presence` with the **current** teacher prompt on the rebuilt
     inputs (do **not** ratify the stale `response` proposals — they were made on
     the old prompt + thin input), then HITL-ratify into `_human_travel_days` /
     `_human_requires_relocation` / `_human_requires_local_presence`.

   Data already present that de-risks this: the teacher `RemoteAnalysis` sits in
   each record's `response` (all 106), `_corrected` is `True` on only 9/106 (92%
   teacher/human agreement), so proposals are strong ratify starting points —
   they just must be **re-generated on current inputs**, not reused. Bump
   `remote_filter_golden_dataset_requirements.md`. **Largest slice; depends on 1.**

1. **Rewire eval to the classifier-native metric** — categorical confusion +
   travel MAE against the new gold fields; update the run-record `metrics` block;
   bump eval `schema_version`. Depends on 2 + 5.

1. *(optional)* **Flag-level gold + eval** — relocation / local-presence bools
   (second HITL pass).

1. **Docs** — update `eval_framework_requirements.md` /
   `remote_filter_eval_tuning.md` to describe the two-tier model + input contract.

______________________________________________________________________

## Related open issues

This proposal reframes or directly addresses several existing issues — these
should be linked (and some possibly re-scoped/closed) at ratification, not
duplicated:

- **#63 — `establish remote_filter eval baseline and pin champion`
  (investigation).** Blocked by this: you cannot pin a meaningful champion while
  the metric scores a policy production ignores. The classifier-native metric
  (slice 4) is the baseline #63 actually wants. **Strong dependency.**
- **#16 — `expand golden dataset and tune remote-filter precision to ≥0.80`.**
  This spec changes what "precision" *means* (per-class categorical, not global
  pass/trash) and the gold expansion is our slice 3 remap+ratify. #16 should be
  re-scoped to target the new metric or folded into slices 3–4.
- **#97 — `false on-site classifications for Diné Development Corporation jobs`.**
  A pure classifier-accuracy bug (per project memory, now the dominant error
  mode). The categorical confusion matrix (slice 1/4) is the tool that measures
  and regression-guards exactly this — #97 becomes a gold-set case + a metric to
  watch, not a one-off investigation.
- **#17 — `decision: timezone policy for remote-filter — hard reject vs soft preference`.** A *policy-layer* decision. This spec cleanly separates that from
  classifier accuracy: whatever #17 decides lives in the gate (unit-tested,
  slice 2), and does not perturb the classifier eval. Worth cross-linking so the
  two-layer split informs the #17 decision.

Not related (checked, ruled out): #300/#325 (frontend filter typing), #31
(local-server provider naming), #218 (frontend legacy travel filters).

______________________________________________________________________

## Resolved decisions (ratified 2026-07-17)

1. **`onsite` remap: RESOLVED by `remote_filter_taxonomy.md`.** The taxonomy adds
   a real `onsite` bucket, so the ~52 legacy `onsite` rows map **directly** — no
   per-row human call, no `onsite_disguised`-vs-`location_restricted` agonizing.
   The remap table above reflects this.

1. **Binary eval: DROP it.** Retire the pass/trash remote-filter eval entirely
   once the categorical classifier metric lands — do not keep it as a secondary
   metric. Rationale: the taxonomy retires the global `passes_remote_filter`
   policy's role in overnight (its slice 4), so scoring it no longer measures
   anything production does. `_human_verdict` is kept as historical provenance
   but no longer scored. (Trade-off accepted: this abandons the standalone-CLI
   binary-eval path, which is not part of the overnight product.)

1. **Flag-level eval: DEFER.** Do not add the `requires_relocation` /
   `requires_local_presence` HITL pass now; add it only if/when such a
   misclassification actually bites. The categorical + travel metrics cover the
   dominant error modes. Under the taxonomy these are extraction-only fields
   gated deterministically in `_gate_user`, so flag-level eval would measure
   extraction quality, not gating. (This makes slice 7 explicitly deferred.)

1. **Log cosmetics: SUBSUMED by `remote_filter_taxonomy.md` slice 4.** Retiring
   the global policy's role in overnight removes the misleading `PASS`/`TRASH`
   log at its source — no separate fix needed here.

1. **Gold re-derivation strategy (slice 5): RESOLVED → hybrid.** Three options
   were on the table: (a) fresh corpus + full relabel (clean, expensive); (b)
   pure back-fill of the existing 106 (cheap, but cross-duplicate
   `search_contexts` is unrecoverable *and* the teacher labels in `response` were
   made on the old prompt + thin input, so ratifying them ports stale judgments);
   (c) **hybrid** — keep the human classification decisions, regenerate the
   input-sensitive structured fields (travel/relocation/local-presence) by
   re-proposing with the current teacher prompt on rebuilt inputs, then ratify.
   **Chosen: (c).** It preserves the expensive human labor and avoids blessing
   stale proposals, at the cost of a re-proposal + ratify pass. Residual gap:
   records with no live duplicate set get synthesized self-provenance only.

1. **Input model scope: RESOLVED → in-memory projection; boundary contract
   deferred.** `RemoteFilterInput` is a *projection* (only the ~8 prompt-read
   fields), not the whole posting — so it cannot itself be the on-disk stage
   handoff without starving downstream stages (skills_fit/DB need the full field
   set). Two real options:

   - **(1) In-memory prompt contract (chosen for this spec).** Built at
     prompt-construction time via `RemoteFilterInput.from_posting(dict)` inside
     `build_search_context`; consumed by `_build_user_message` / `analyze_remote`
     and the eval. `postings.jsonl` stays an untyped dict handoff. Contained to
     `src/agents/remote_filter/`; fully satisfies the eval-fidelity + drift-1
     goals; no pipeline/DB touch.
   - **(2) Pipeline-boundary contract (deferred to its own spec).** A *broader*
     `ConsolidatedPosting` model validated on `consolidate_run` write +
     `load_raw_jobs` read, with `RemoteFilterInput = ConsolidatedPosting.to_classifier_input()`. This is the fullest expression
     of the CLAUDE.md data-boundary rule for the scrape→consolidate→classify
     handoff, but requires modeling progressive mid-pipeline enrichment
     (`_prefilter_*` / `_remote_analysis`) and brushes the
     `pipe.consolidated_postings` / `posting_ref` jsonb story — a data-layer
     refactor that would balloon this eval-focused spec and couple its delivery
     to riskier change.

   **Decision:** ship (1) here; file (2) as a follow-up spec. Design
   `RemoteFilterInput` as a pure projection with `from_posting(dict)` so that
   when `ConsolidatedPosting` lands, promotion is a single added
   `from_consolidated(cp)` classmethod with no change to the prompt builder or
   eval. Do **not** half-validate `postings.jsonl` inside the agent — that
   misplaces pipeline-boundary responsibility.

______________________________________________________________________

## Changelog

- **2026-07-16 — draft.** Initial proposal. Motivated by the observation that
  `scripts/run_remote_filter_eval.py` scores the global `passes_remote_filter`
  policy, which the overnight pipeline treats as advisory
  (`scoring._gate_user` is the operative per-user gate and has no eval). Gold
  set found to already carry categorical labels in `_human_policy`, reducing the
  migration to a remap + ratify pass.
- **2026-07-16 — reconciled with taxonomy.** `remote_filter_taxonomy.md` drafted
  and made a dependency. Metric arity 5-way → **4-way** axis; open question 1
  (`onsite` remap) resolved (direct map, taxonomy adds the bucket); the gold
  remap burden collapses from "~58 HITL rows" to ~5 field-fills; open question 4
  (log cosmetics) subsumed by the taxonomy's global-policy retirement.
- **2026-07-16 — input drift added.** Second drift identified: the eval
  hand-builds `search_context` and never calls `build_search_context`, so it
  feeds a thinner prompt than production; and 0/106 gold records carry the
  `search_contexts` provenance the Phase 13 consolidation now attaches. Added the
  eval-input-fidelity requirement, a `RemoteFilterInput`/`SearchProvenance`
  Pydantic input contract as the preferred fix (formalizing the ad-hoc prompt
  dict per the CLAUDE.md data-boundary rule), and re-sliced accordingly (model is
  now slice 1; gold re-derivation must source from post-consolidation records).
- **2026-07-17 — ratified.** `remote_filter_taxonomy.md` ratified; its four
  decisions flow through here (4-way axis; travel display-only → not gated/eval'd
  for gating; `unclear` fail-open in the gate tests). Two remaining open
  questions decided (self-review): **binary eval dropped** (not demoted — the
  global policy it scored is retired), and **flag-level eval deferred** (slice 7
  stays optional/deferred). Status → RATIFIED; issues may now be derived.
