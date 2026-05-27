# Eval Framework — Architecture Reference

**Spec:** [eval_framework_requirements.md](eval_framework_requirements.md)

All seven success criteria (SC-1 through SC-7) are complete. 319/319 tests passing.

## Design decisions

| SC   | What it does                                                                                                       | Key files                                                    |
| ---- | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------ |
| SC-1 | Pluggable logging via `RunLogger` Protocol — `JsonlRunLogger` ships, `MLFlowRunLogger` stub proves the interface   | `src/agent_eval/logger.py`                                   |
| SC-2 | Durable run provenance — `build_run_record()` captures git SHA, config hash, env snapshot, full confusion matrix   | `src/agent_eval/provenance.py`, `src/agent_eval/metrics.py`  |
| SC-3 | Deterministic config — `--model`, `--temperature`, `--provider`, `--run-id` overrides; all reflected in run record | `scripts/run_remote_filter_eval.py`                          |
| SC-4 | Artifact isolation — `data/eval/` gitignored, `runs.jsonl` append-only, secrets redacted via `_sanitize()`         | `src/agent_eval/logger.py`                                   |
| SC-5 | CLI comparison — `compare_evals.py` with `--last N`, `--sort-by`, `--diff`                                         | `scripts/compare_evals.py`                                   |
| SC-6 | Parallel eval — `ThreadPoolExecutor` with `--workers N`; workers excluded from provenance                          | `scripts/run_remote_filter_eval.py`                          |
| SC-7 | Batch eval — `submit_eval_batch.py` / `poll_eval_batch.py` against OpenAI Batch API; sidecar metadata schema       | `scripts/submit_eval_batch.py`, `scripts/poll_eval_batch.py` |

## Baseline metrics (2026-05-16, gpt-4o-mini, 104 records)

```
TP/FP/TN/FN: 29 / 12 / 61 / 2
accuracy:    0.8654
precision:   0.7073   ← main tuning target (goal ≥ 0.80)
recall:      0.9355
f1:          0.8056
```

Primary failure mode: false positives on `onsite_disguised` and `location_restricted` jobs.

## Open work

Precision tuning and golden dataset expansion tracked on GitHub — `gh issue list` or <https://github.com/fieryWalrus1002/job-scraper-9000/issues>
