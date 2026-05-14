# Eval Framework Requirements

**Date:** 2026-05-14  
**Branch:** feature/remote-filter-eval

## Objective

Implement a reproducible, file-based evaluation tracking system to measure LLM classification accuracy across different models, prompts, and hyperparameter configurations. Must use a modular logging interface to support future cloud tracking integrations without changes to eval logic.

---

## Success Criteria

### SC-1 — Pluggable Logging Architecture

Evaluation scripts must not perform inline file I/O for telemetry.

- Define a `RunLogger` `Protocol` (structural subtyping, not ABC) with a single method: `log_run(record: dict) -> None`
- Implement `JsonlRunLogger(RunLogger)` that appends records to a configurable path (default: `data/eval/runs.jsonl`)
- `run_eval.py` must accept a `RunLogger` instance via its public interface; swapping to a future `MlflowRunLogger` must require zero changes to eval logic
- A failure in `log_run()` must be logged as a warning and must not suppress or abort eval results

### SC-2 — Durable Run Provenance

Every execution must produce a single JSONL record with all of the following fields:

| Field | Description |
| --- | --- |
| `schema_version` | Semver string (e.g. `"1.0.0"`) — increment when fields are added or changed |
| `run_id` | `YYYYMMDD_HHMMSS_<4-char hex>` — sortable and unique; when `--run-id` supplies a custom label, the logger must reject it if the value already exists in `runs.jsonl` |
| `timestamp` | ISO 8601 UTC |
| `git.commit` | Short SHA from `git rev-parse --short HEAD` — pins dependencies, config, and prompt files to a reproducible state |
| `git.dirty` | Boolean — if `true`, the commit hash alone does not fully describe the run environment |
| `gold_file` | Relative path to the gold JSONL used |
| `gold_hash` | `sha256:<hex>` of the gold file bytes — detects silent dataset drift |
| `prompt_hash` | `sha256:<hex>` of the **resolved system prompt string** passed to the LLM — not the source file, so dynamic composition is captured correctly (first 8 hex chars as display label) |
| `config.provider` | LLM provider as resolved at runtime (after any CLI overrides) |
| `config.model` | Model name as resolved at runtime |
| `config.temperature` | Temperature as resolved at runtime |
| `config.policy_thresholds` | Full `policy_thresholds` block from the config YAML |
| `config.config_file` | Path to the YAML used |
| `env.python_version` | Output of `platform.python_version()` — behavior can shift across minor versions independent of `uv.lock` |
| `env.platform` | Output of `platform.platform()` — OS/architecture; `uv.lock` is cross-platform and does not capture this |
| `env.uv_version` | Output of `uv --version` — resolver behavior can differ across UV versions even with the same lock; if `uv` is unavailable, log `null` and emit a warning without failing the run |
| `env.uv_lock_hash` | `sha256:<hex>` of `uv.lock` — detects accidental edits to the lock without a corresponding code change; makes the record self-contained without requiring a git checkout |
| `metrics.evaluated` | Records that completed inference and received a verdict |
| `metrics.skipped` | Records dropped before inference (missing description, invalid verdict, agent error) |
| `metrics.total` | `evaluated + skipped` |
| `metrics.prevalence` | `(tp + fn) / evaluated` — positive-class rate in the gold set; flags dataset drift between runs |
| `metrics.tp/fp/tn/fn` | Raw confusion matrix counts |
| `metrics.accuracy` | `(tp + tn) / evaluated` — skipped records have no verdict and must not be in the denominator |
| `metrics.precision` | `tp / (tp + fp)` — positive-class precision |
| `metrics.recall` | `tp / (tp + fn)` — positive-class recall |
| `metrics.f1` | `2 * precision * recall / (precision + recall)` — positive-class F1 |
| `mismatch_file` | Relative path to the corresponding mismatch JSONL, or `null` if none |
| `mismatch_schema_version` | Semver string for mismatch record format; bump when fields change |

### SC-3 — Deterministic Configuration

CLI parameter overrides must not modify base YAML files.

- `--model`, `--temperature`, `--provider` override the loaded config in memory only
- The run record's `config.*` fields must reflect the resolved (post-override) values, not the YAML defaults
- `--run-id <label>` allows a human-readable label to replace the auto-generated timestamp ID

### SC-4 — Artifact Isolation & Hygiene

- Each mismatch file must be named `mismatches_{run_id}.jsonl` and include a `run_id` field in every record
- Each mismatch record must include: `record_id` (`dedup_hash` from the gold record), `gold` (human verdict), `pred` (agent verdict), `human_policy` (e.g. `"fully_remote"`, `"hybrid"`), and `reason` (agent's filter decision) — `human_policy` is required to categorize failure by edge-case type without reloading the gold file
- `data/eval/runs.jsonl` and `data/eval/mismatches_*.jsonl` must be excluded from source control via `.gitignore`
- The `runs.jsonl` sink must append only — existing records must never be modified or deleted by the eval script
- `RunLogger` must explicitly strip any API keys, tokens, or secret material from the config snapshot before writing; the `config.*` block must contain only provider, model, temperature, and policy thresholds

### SC-5 — CLI-First Comparison

`scripts/compare_evals.py` must:

- Read `data/eval/runs.jsonl` (overridable via `--runs-file`)
- Print a table with columns: `run_id`, `date`, `model`, `temperature`, `total`, `skipped`, `accuracy`, `precision`, `recall`, `f1`
- Format metric columns to 4 decimal places for stable diffs and scanability
- Support `--last N` to show the N most recent runs
- Support `--sort-by <metric>` (valid values: `timestamp`, `accuracy`, `precision`, `recall`, `f1`; default: `timestamp`)
- Support `--diff <run_id_a> <run_id_b>` to print side-by-side metrics for two runs with directional indicators (`↑`/`↓`/`=`)
- Exit 0 and print a clear message when `runs.jsonl` does not exist yet

---

## Examples

Example `runs.jsonl` record:

```json
{"schema_version":"1.1.0","run_id":"20260514_193055_a7f3","timestamp":"2026-05-14T19:30:55Z","git":{"commit":"3f7c2b1","dirty":false},"gold_file":"data/eval/ground_truth.jsonl","gold_hash":"sha256:8d4fb5a7b2f6d6f08e9d6a932c9d0f7f7c1a4b9f09cfe1b8d3c8a2f35ef0a1b9","prompt_hash":"sha256:91c3f7a5d0e6fef5b08f0fd5c7bde40a5c02f273a44b3a2b83d8c6f92b6a12b1","config":{"provider":"openai","model":"gpt-4o-mini","temperature":0.1,"policy_thresholds":{"disallowed_classifications":["onsite_disguised","hybrid","onsite"],"travel":{"max_estimated_days_per_year":15,"prohibited_categories":["remote_with_frequent_travel"]},"relocation":{"allow_required_relocation":false,"allow_local_presence_required":false},"uncertainty":{"on_unclear_classification":"reject"},"timezone":{"user_timezone":"PST","rejected_timezone_keywords":["EST","ET","Eastern","Eastern time","Eastern Standard Time"]}},"config_file":"config/agent/remote_agent.yml"},"env":{"python_version":"3.11.9","platform":"Linux-6.8.0-44-generic-x86_64-with-glibc2.39","uv_version":"0.4.18","uv_lock_hash":"sha256:3b2f4b3c9a0cfe0d8f6b5bca7deccf4b1a7d2d5ef85bcf2b6e5c9aa19d2ed2b8"},"metrics":{"evaluated":48,"skipped":2,"total":50,"prevalence":0.1458,"tp":6,"fp":2,"tn":39,"fn":1,"accuracy":0.9375,"precision":0.7500,"recall":0.8571,"f1":0.8000},"mismatch_file":"data/eval/mismatches_20260514_193055_a7f3.jsonl","mismatch_schema_version":"1.0.0"}
```

Example mismatch record (`mismatches_*.jsonl`):

```json
{"run_id":"20260514_193055_a7f3","record_id":"606ba385","gold":"pass","pred":"trash","reason":"Model rejected due to EST timezone requirement; human policy was fully_remote."}
```

---

## Extensibility

- Optional fields (e.g., `agent_latency_ms`, `token_usage`) may be added to run records without a schema bump, as long as existing required fields remain unchanged

---

## Out of Scope

- MLflow, Azure ML, or any external tracking service (interface must support it; integration is not required)
- SQLite per-record storage
- Fine-tuning or teacher model integration
- Streamlit or web UI
- CI/CD gating (e.g. fail a PR when F1 drops below threshold) — the machine-readable `runs.jsonl` format is designed to support this; implementation belongs in a CI spec
