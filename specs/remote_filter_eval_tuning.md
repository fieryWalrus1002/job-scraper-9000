# Remote Filter Eval Tuning Notes

_Last updated: 2026-05-16_

## Purpose

The remote-filter eval framework is now implemented through SC-7. The next work is not more eval infrastructure; it is eval-driven data quality, policy tuning, and prompt tuning.

This note tracks the current baseline and the likely next sprint for improving remote-filter quality.

---

## Current smoke baseline

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

| Metric | Value |
| --- | ---: |
| Accuracy | 0.8654 |
| Precision | 0.7073 |
| Recall | 0.9355 |
| F1 | 0.8056 |
| TP / FP / TN / FN | 29 / 12 / 61 / 2 |

Mismatch file:

```text
data/eval/mismatches_smoke_parallel_20260516_045209_a6da.jsonl
```

---

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

---

## Review workflow

For each mismatch in the smoke run, classify the cause as one of:

| Category | Meaning |
| --- | --- |
| Gold label issue | Human label should be corrected in `data/eval/ground_truth.jsonl` |
| Prompt failure | Model classified the remote policy incorrectly |
| Policy failure | Model extracted reasonable fields, but `passes_remote_filter()` allowed/rejected incorrectly |
| Ambiguous posting | Job text genuinely lacks enough signal; decide preferred policy |
| Dataset coverage gap | Need more similar examples in the gold set |

Recommended process:

1. Open the mismatch JSONL.
2. Find each `record_id` in `data/eval/ground_truth.jsonl` by `dedup_hash` prefix.
3. Inspect:
   - original job location
   - job description
   - `_human_verdict`
   - `_human_policy`
   - model `_filter_reason` / predicted policy if available
4. Decide whether to:
   - correct the gold record through the review UI or direct append-only re-review
   - adjust `config/agent/remote_agent.yml`
   - adjust `prompts/remote_agent/system_prompt.txt`
   - add more examples to the gold set
5. Rerun eval with a new run ID.
6. Compare with:

```bash
uv run scripts/compare_evals.py --last 10
```

---

## Candidate tuning targets

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

---

## Success target for next sprint

A reasonable next target on the 100+ record gold set:

| Metric | Target |
| --- | ---: |
| Precision | ≥ 0.80 |
| Recall | ≥ 0.90 |
| F1 | ≥ 0.85 |

Prioritize precision improvement without materially harming recall.

---

## Not in scope for this tuning sprint

- Building the Phase 3 skills-fit agent
- Fine-tuning or local model distillation
- Changing ingestion scrapers
- CI gating on eval metrics

Those become more valuable after the gold set and remote-filter policy stabilize.
