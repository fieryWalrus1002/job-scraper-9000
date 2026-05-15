# Eval Framework — Implementation Status

**Branch:** feature/remote-filter-eval  
**Spec:** [eval_framework_requirements.md](eval_framework_requirements.md)

---

## SC-1 — Pluggable Logging Architecture

| Task | Status | Location |
| --- | --- | --- |
| `RunLogger` Protocol defined | ✅ done | `src/eval/logger.py` |
| `JsonlRunLogger` implemented | ✅ done | `src/eval/logger.py` |
| `MLFlowRunLogger` stub (Protocol proof) | ✅ done | `src/eval/logger.py` |
| Non-fatal I/O failure → warning | ✅ done | `src/eval/logger.py` |
| Duplicate `run_id` → `ValueError` | ✅ done | `src/eval/logger.py` |
| Driver accepts `RunLogger` via DI | ✅ done | `scripts/run_remote_filter_eval.py` |

---

## SC-2 — Durable Run Provenance

| Task | Status | Location |
| --- | --- | --- |
| `hash_bytes` / `hash_string` / `hash_file` primitives | ✅ done | `src/eval/provenance.py` |
| `generate_run_id()` | ✅ done | `src/eval/provenance.py` |
| `_collect_env()` — python, platform, uv version + lock hash | ✅ done | `src/eval/provenance.py` |
| `build_run_record()` — full SC-2 schema | ✅ done | `src/eval/provenance.py` |
| Git short SHA (7 chars, via `git_info`) | ✅ done | `src/eval/provenance.py` |
| `compute_metrics()` — confusion matrix → metric dict | ✅ done | `src/eval/metrics.py` |
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
| `runs.jsonl` append-only enforced | ✅ done | `src/eval/logger.py` |
| Secret redaction in `_sanitize()` | ✅ done | `src/eval/logger.py` |
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

## Tests

| Task | Status | Location |
| --- | --- | --- |
| `tests/eval/` directory + stubs (19 tests) | ✅ done | `tests/eval/` |
| `test_logger.py` — implement all 10 stubs | ✅ done | `tests/eval/test_logger.py` |
| `test_metrics.py` — implement all 9 stubs | ✅ done | `tests/eval/test_metrics.py` |

---

## All SCs complete — 314/314 tests passing
