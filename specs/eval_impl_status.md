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
| Driver accepts `RunLogger` via DI | ⬜ todo | `scripts/run_remote_filter_eval.py` |

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
| Driver calls `build_run_record()` and `log_run()` | ⬜ todo | `scripts/run_remote_filter_eval.py` |
| Mismatch file renamed `mismatches_{run_id}.jsonl` | ⬜ todo | `scripts/run_remote_filter_eval.py` |

---

## SC-3 — Deterministic Configuration

| Task | Status | Location |
| --- | --- | --- |
| `--model` override (in-memory only) | ⬜ todo | `scripts/run_remote_filter_eval.py` |
| `--temperature` override | ⬜ todo | `scripts/run_remote_filter_eval.py` |
| `--provider` override | ⬜ todo | `scripts/run_remote_filter_eval.py` |
| `--run-id` custom label | ⬜ todo | `scripts/run_remote_filter_eval.py` |
| Overrides reflected in run record `config.*` | ⬜ todo | `scripts/run_remote_filter_eval.py` |

---

## SC-4 — Artifact Isolation & Hygiene

| Task | Status | Location |
| --- | --- | --- |
| `data/eval/*.jsonl` excluded from git | ✅ done | `.gitignore` (`data/**/*.jsonl`) |
| `runs.jsonl` append-only enforced | ✅ done | `src/eval/logger.py` |
| Secret redaction in `_sanitize()` | ✅ done | `src/eval/logger.py` |
| Mismatch records include `run_id`, `record_id`, `gold`, `pred`, `human_policy`, `reason` | ⬜ todo | `scripts/run_remote_filter_eval.py` |

---

## SC-5 — CLI-First Comparison

| Task | Status | Location |
| --- | --- | --- |
| `compare_evals.py` — table output | ⬜ todo | `scripts/compare_evals.py` |
| `--last N` | ⬜ todo | `scripts/compare_evals.py` |
| `--sort-by <metric>` | ⬜ todo | `scripts/compare_evals.py` |
| `--diff <run_id_a> <run_id_b>` | ⬜ todo | `scripts/compare_evals.py` |
| Graceful empty-file exit | ⬜ todo | `scripts/compare_evals.py` |
| 4 decimal place formatting | ⬜ todo | `scripts/compare_evals.py` |

---

## Tests

| Task | Status | Location |
| --- | --- | --- |
| `tests/eval/` directory + stubs (19 tests) | ✅ done | `tests/eval/` |
| `test_logger.py` — implement all 10 stubs | ✅ done | `tests/eval/test_logger.py` |
| `test_metrics.py` — implement all 9 stubs | ✅ done | `tests/eval/test_metrics.py` |

---

## Remaining work order

1. `src/eval/metrics.py` — `compute_metrics()`, unblocks test_metrics.py
2. `tests/eval/test_logger.py` — implement stubs (no LLM needed, pure/tmp_path)
3. `tests/eval/test_metrics.py` — implement stubs (pure functions)
4. `scripts/run_remote_filter_eval.py` — full rewrite: DI, provenance, CLI overrides, `MismatchRecord(BaseModel)`, mismatch schema
5. `scripts/compare_evals.py` — new script, SC-5
