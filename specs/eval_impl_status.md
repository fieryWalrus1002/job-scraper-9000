# Eval Framework — Implementation Status

**Branch:** feature/remote-filter-eval  
**Spec:** [eval_framework_requirements.md](eval_framework_requirements.md)

---

## Immediate Cleanup / Next Progress

| Task | Status | Location |
| --- | --- | --- |
| Align prompt provenance paths — canonical `system_prompt.txt` files now drive runtime, eval, and batch metadata | ✅ done | `prompts/remote_agent/system_prompt.txt`, `prompts/remote_agent_teacher/system_prompt.txt`, `src/agents/remote_filter/utils.py`, `scripts/run_remote_filter.py`, `scripts/run_remote_filter_eval.py`, `scripts/prepare_batch.py`, `scripts/merge_batch_results.py` |
| Update docs that lag implementation status | ⬜ pending | `README.md`, `scripts/README.md`, `src/review_ui/README.md`, `project-status.md`, `specs/project_impl_status.md` |
| Package install cleanup — rename generic eval package to `agent_eval` and include reusable support packages beyond `job_scraper`, `agents`, and `ci` | ✅ done | `pyproject.toml` (`src/agent_eval`, `src/utils`, `src/review_ui`) |
| Keep Phase 2 status focused on eval/data quality before starting skills-fit scorer | ⬜ pending | `project-status.md`, `specs/project_impl_status.md` |

---

## SC-1 — Pluggable Logging Architecture

| Task | Status | Location |
| --- | --- | --- |
| `RunLogger` Protocol defined | ✅ done | `src/agent_eval/logger.py` |
| `JsonlRunLogger` implemented | ✅ done | `src/agent_eval/logger.py` |
| `MLFlowRunLogger` stub (Protocol proof) | ✅ done | `src/agent_eval/logger.py` |
| Non-fatal I/O failure → warning | ✅ done | `src/agent_eval/logger.py` |
| Duplicate `run_id` → `ValueError` | ✅ done | `src/agent_eval/logger.py` |
| Driver accepts `RunLogger` via DI | ✅ done | `scripts/run_remote_filter_eval.py` |

---

## SC-2 — Durable Run Provenance

| Task | Status | Location |
| --- | --- | --- |
| `hash_bytes` / `hash_string` / `hash_file` primitives | ✅ done | `src/agent_eval/provenance.py` |
| `generate_run_id()` | ✅ done | `src/agent_eval/provenance.py` |
| `_collect_env()` — python, platform, uv version + lock hash | ✅ done | `src/agent_eval/provenance.py` |
| `build_run_record()` — full SC-2 schema | ✅ done | `src/agent_eval/provenance.py` |
| Git short SHA (7 chars, via `git_info`) | ✅ done | `src/agent_eval/provenance.py` |
| `compute_metrics()` — confusion matrix → metric dict | ✅ done | `src/agent_eval/metrics.py` |
| Driver calls `build_run_record()` and `log_run()` | ✅ done | `scripts/run_remote_filter_eval.py` |
| Mismatch file renamed `mismatches_{run_id}.jsonl` | ✅ done | `scripts/run_remote_filter_eval.py` |

---

## SC-3 — Deterministic Configuration

| Task | Status | Location |
| --- | --- | --- |
| `--model` override (in-memory only) | ✅ done | `scripts/run_remote_filter_eval.py` |
| `--temperature` override | ✅ done | `scripts/run_remote_filter_eval.py` |
| `--provider` override | ✅ done | `scripts/run_remote_filter_eval.py` |
| `--run-id` custom label | ✅ done | `scripts/run_remote_filter_eval.py` |
| Overrides reflected in run record `config.*` | ✅ done | `scripts/run_remote_filter_eval.py` |

---

## SC-4 — Artifact Isolation & Hygiene

| Task | Status | Location |
| --- | --- | --- |
| `data/eval/*.jsonl` excluded from git | ✅ done | `.gitignore` (`data/**/*.jsonl`) |
| `runs.jsonl` append-only enforced | ✅ done | `src/agent_eval/logger.py` |
| Secret redaction in `_sanitize()` | ✅ done | `src/agent_eval/logger.py` |
| Mismatch records include `run_id`, `record_id`, `gold`, `pred`, `human_policy`, `reason` | ✅ done | `scripts/run_remote_filter_eval.py` |

---

## SC-5 — CLI-First Comparison

| Task | Status | Location |
| --- | --- | --- |
| `compare_evals.py` — table output | ✅ done | `scripts/compare_evals.py` |
| `--last N` | ✅ done | `scripts/compare_evals.py` |
| `--sort-by <metric>` | ✅ done | `scripts/compare_evals.py` |
| `--diff <run_id_a> <run_id_b>` | ✅ done | `scripts/compare_evals.py` |
| Graceful empty-file exit | ✅ done | `scripts/compare_evals.py` |
| 4 decimal place formatting | ✅ done | `scripts/compare_evals.py` |

---

## SC-6 — Parallel Evaluation (fast experimentation)

| Task | Status | Location |
| --- | --- | --- |
| `--workers N` flag added to argument parser | ✅ done | `scripts/run_remote_filter_eval.py` |
| `ThreadPoolExecutor` dispatch with in-order result collection | ✅ done | `scripts/run_remote_filter_eval.py` |
| `--workers` excluded from run provenance record | ✅ done | `scripts/run_remote_filter_eval.py` |
| Clean Ctrl+C exit preserved under parallel execution | ✅ done | `scripts/run_remote_filter_eval.py` |

---

## SC-7 — Batch Evaluation (regression testing)

| Task | Status | Location |
| --- | --- | --- |
| `submit_eval_batch.py` — build + submit batch, write sidecar | ✅ done | `scripts/submit_eval_batch.py` |
| `poll_eval_batch.py` — check status, download, compute metrics, log run record | ✅ done | `scripts/poll_eval_batch.py` |
| Sidecar schema `{batch_id, run_id, submitted_at, gold_file, gold_hash, config, prompt_hash}` | ✅ done | `scripts/submit_eval_batch.py` |
| `--sidecar <path>` override; defaults to most recent sidecar | ✅ done | `scripts/poll_eval_batch.py` |
| Clear error if `--provider ollama` passed to submit script | ✅ done | `scripts/submit_eval_batch.py` |
| Run record written by poll script is SC-2 compliant | ✅ done | `scripts/poll_eval_batch.py` |

---

## Tests

| Task | Status | Location |
| --- | --- | --- |
| `tests/agent_eval/` directory + stubs (19 tests) | ✅ done | `tests/agent_eval/` |
| `test_logger.py` — implement all 10 stubs | ✅ done | `tests/agent_eval/test_logger.py` |
| `test_metrics.py` — implement all 9 stubs | ✅ done | `tests/agent_eval/test_metrics.py` |
| Parallel eval order/count tests | ✅ done | `tests/test_run_remote_filter_eval.py` |
| Batch eval request/result tests | ✅ done | `tests/test_eval_batch.py` |

---

## SC-1 through SC-7 complete — 319/319 tests passing

## Smoke Test Results

Latest real synchronous eval smoke test:

```text
run_id:    smoke_parallel_20260516_045209_a6da
command:   uv run scripts/run_remote_filter_eval.py --workers 4 --run-id smoke_parallel
records:   104 evaluated, 0 skipped
model:     gpt-4o-mini
temp:      0.1
TP/FP/TN/FN: 29 / 12 / 61 / 2
accuracy:  0.8654
precision: 0.7073
recall:    0.9355
f1:        0.8056
```

Interpretation: recall is strong, but precision needs work. The current main tuning target is reducing false positives where onsite/location-restricted jobs are allowed through as pass.

## Broader docs cleanup and gold dataset balancing still pending
