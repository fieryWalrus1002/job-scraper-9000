# Remote Filter Eval Tuning Notes

_Last updated: 2026-07-20_

## Purpose

The remote-filter eval framework is now implemented through SC-7. The next work is not more eval infrastructure; it is eval-driven data quality, policy tuning, and prompt tuning.

This note tracks the current baseline and the likely next sprint for improving remote-filter quality.

> **Two-tier model (Phase 31 update).** The remote-filter eval no longer scores a
> global binary pass/trash policy. Phase 31
> (`remote_filter_eval_decoupling.md`, RATIFIED) split it into:
>
> - **Tier 1 — LLM classifier eval:** `run_remote_filter_eval.py` scores the
>   model's extraction on a **policy-independent categorical axis** (per-class
>   precision/recall/F1, macro + micro, N×N confusion matrix via
>   `compute_categorical_metrics`), plus **travel MAE** as extraction quality only
>   (travel is not gated). Axis defined in `remote_filter_taxonomy.md`.
> - **Tier 2 — deterministic policy gates:** `_gate_user` applies per-user policy
>   and is covered by **unit tests** (`tests/pipeline/test_gate_user.py`), *not* the
>   eval harness. `passes_remote_filter` (the old global gate) is retired.
>
> Both share the `RemoteFilterInput` / `SearchProvenance` input contract.
> "Precision" below now means **per-class categorical precision**, not global
> pass/trash. Ongoing classifier + gold-curation tuning is tracked in
> `remote_filter_classifier_tuning.md` (Phase 32), which also retires the `unclear`
> class → 3-way axis.

______________________________________________________________________

## Current smoke baseline

> **Legacy (binary) baseline.** The numbers below are the retired binary
> pass/trash metric and are kept for historical comparison only. Current runs
> report the categorical metrics (per-class + confusion matrix + travel MAE); see
> `remote_filter_classifier_tuning.md` for the first categorical baseline
> (run `20260720_155630_14cf`: micro accuracy 0.9327).

Command:

```bash
uv run scripts/run_remote_filter_eval.py --workers 4 --run-id smoke_parallel
```

Run:

```text
smoke_parallel_20260516_045209_a6da
```

Dataset:

```text
data/eval/ground_truth.jsonl
104 evaluated, 0 skipped
```

Metrics:

| Metric            |            Value |
| ----------------- | ---------------: |
| Accuracy          |           0.8654 |
| Precision         |           0.7073 |
| Recall            |           0.9355 |
| F1                |           0.8056 |
| TP / FP / TN / FN | 29 / 12 / 61 / 2 |

Mismatch file:

```text
data/eval/mismatches_smoke_parallel_20260516_045209_a6da.jsonl
```

______________________________________________________________________

## Interpretation

Recall is strong: the agent is catching most jobs labeled as acceptable remote roles.

Precision is the main weakness: too many jobs labeled `trash` by the human reviewer are being predicted as `pass`.

The dominant failure pattern appears to be false positives where roles are:

- onsite but not explicitly rejected by the model/policy
- onsite-disguised
- location-restricted
- unclear but allowed through as pass

There are also a small number of false negatives involving timezone policy:

- human label: `pass`
- model/policy result: `trash`
- reason: `timezone_mismatch:Eastern Time Zone` or `timezone_mismatch:EST`

These may be policy decisions rather than model failures.

______________________________________________________________________

## Review workflow

For each mismatch in the smoke run, classify the cause as one of:

| Category             | Meaning                                                                                                                                                                                 |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Gold label issue     | Human label should be corrected in `data/eval/ground_truth.jsonl`                                                                                                                       |
| Prompt failure       | Model classified the remote policy incorrectly                                                                                                                                          |
| Policy failure       | Gate (`_gate_user`) allowed/rejected incorrectly given correct extraction — **now caught by gate unit tests, not this eval** (Tier 2); the classifier eval only sees extraction quality |
| Ambiguous posting    | Job text genuinely lacks enough signal; decide preferred policy                                                                                                                         |
| Dataset coverage gap | Need more similar examples in the gold set                                                                                                                                              |

Recommended process:

1. Open the mismatch JSONL.
1. Find each `record_id` in `data/eval/ground_truth.jsonl` by `dedup_hash` prefix.
1. Inspect:
   - original job location
   - job description
   - `_human_verdict`
   - `_human_policy`
   - model `_filter_reason` / predicted policy if available
1. Decide whether to:
   - correct the gold record through the review UI or direct append-only re-review
   - adjust `config/agent/remote_agent.yml`
   - adjust `prompts/remote_agent/system_prompt.txt`
   - add more examples to the gold set
1. Rerun eval with a new run ID.
1. Compare with:

```bash
uv run scripts/compare_evals.py --last 10
```

______________________________________________________________________

## Candidate tuning targets

> Superseded in large part by Phase 32 (`remote_filter_classifier_tuning.md`),
> which is the current home for classifier + gold-curation tuning. The items below
> predate the categorical metric and the classifier/gate split — read them as
> background; the live plan (search-provenance over-weighting, gold re-ratification,
> `unclear` retirement, travel-metric coverage) lives in the Phase 32 spec.

### 1. Reduce onsite false positives

Likely prompt/policy direction:

- Treat named office locations with no explicit remote language as stronger onsite evidence.
- Treat region/city-specific business roles conservatively unless remote language is explicit.
- Ensure model does not over-trust search context when the body implies local presence.

### 2. Revisit location-restricted policy

Current config intentionally does not blanket-reject `location_restricted`; compatibility checks handle some cases.

Need to decide:

- Should `location_restricted` pass if compatible with `USER_LOCATION=USA`?
- Should state/city restrictions require manual review instead?
- Should non-engineering/business roles with local territories be rejected more aggressively?

### 3. Revisit timezone policy

False negatives show some `pass` jobs rejected for Eastern/EST requirements.

Need to decide:

- Is Eastern-only actually unacceptable for the user?
- Are timezone requirements hard requirements or soft preferences?
- Should the model extract only mandatory timezone constraints more conservatively?

### 4. Balance the gold dataset

Current dataset is useful but still relatively small and imbalanced.

Next target:

- Add more true-pass remote roles.
- Add more hard negative edge cases:
  - remote-in-title but onsite in body
  - remote but city/state restricted
  - travel-heavy remote
  - timezone-restricted remote
  - ambiguous location text

______________________________________________________________________

## Success target for next sprint

> These targets were written against the binary pass/trash metric. Under the
> categorical metric they map to **per-class** precision/recall (esp. `remote`
> recall — the "don't drop a good job" number) and are re-scoped in Phase 32 /
> **#16**. Retained for continuity.

A reasonable next target on the 100+ record gold set:

| Metric    | Target |
| --------- | -----: |
| Precision | ≥ 0.80 |
| Recall    | ≥ 0.90 |
| F1        | ≥ 0.85 |

Prioritize precision improvement without materially harming recall.

______________________________________________________________________

## Not in scope for this tuning sprint

- Building the Phase 3 skills-fit agent
- Fine-tuning or local model distillation
- Changing ingestion scrapers
- CI gating on eval metrics

Those become more valuable after the gold set and remote-filter policy stabilize.

______________________________________________________________________

## Changelog

- **2026-07-20 — Phase 31 two-tier update.** Recast this note for the decoupled
  eval: added the two-tier model (categorical classifier eval vs. unit-tested
  gates) to Purpose, marked the binary smoke baseline as legacy, updated metric
  semantics to per-class categorical, retired the `passes_remote_filter` reference
  in the mismatch-triage table, and pointed ongoing tuning at Phase 32
  (`remote_filter_classifier_tuning.md`). See `remote_filter_eval_decoupling.md`
  and `remote_filter_taxonomy.md`.
