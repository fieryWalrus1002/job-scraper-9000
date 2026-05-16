# scripts/

One-off data pipeline scripts that move job data through the medallion stages. Run them in order to go from raw scraped jobs to a human-verified golden dataset.

## Full Workflow

```
data/raw/*.jsonl                      ← scraped job records (Bronze)
    │
    ├─ prepare_batch.py               → data/raw/gpt_teacher_batch.jsonl
    │       [upload to OpenAI Batch API, download results]
    ├─ merge_batch_results.py         → data/staging/to_review.jsonl     (Silver)
    │       [run Streamlit HITL UI]
    └─ eval/ground_truth.jsonl        ← human-verified records            (Gold)
```

---

## Scripts

### `prepare_batch.py`

Reads raw jobs and produces an [OpenAI Batch API](https://platform.openai.com/docs/guides/batch) request file.

```bash
python scripts/prepare_batch.py
```

**Input:** `data/raw/scraped_jobs.jsonl`
**Output:** `data/raw/gpt_teacher_batch.jsonl`

After running, upload the output file to the OpenAI Batch API dashboard (or via API), wait for completion, and download the results file.

---

### `merge_batch_results.py`

Joins the downloaded OpenAI batch results back onto the original job records and writes the merged staging file that the review UI reads.

```bash
python scripts/merge_batch_results.py \
    --jobs    data/raw/scraped_jobs.jsonl \
    --results data/raw/gpt_teacher_results.jsonl \
    --output  data/staging/to_review.jsonl
```

| Flag | Default | Description |
|---|---|---|
| `--jobs` | `data/raw/scraped_jobs.jsonl` | Original jobs file fed to `prepare_batch.py` |
| `--results` | `data/raw/gpt_teacher_results.jsonl` | Downloaded batch results from OpenAI |
| `--output` | `data/staging/to_review.jsonl` | Merged output for the review UI |
| `--append` | off | Append to output instead of overwriting |

Items where the batch API returned an error are logged and skipped.

---

### `sample_for_review.py`

Pulls a random sample of raw job records into staging. Useful for spot-checking data quality without running the full teacher pipeline.

```bash
python scripts/sample_for_review.py
```

**Input:** `data/raw/pass.jsonl`
**Output:** `data/staging/review_batch.jsonl`

Edit `create_sample_batch()` arguments directly to change the source file or sample size (default `n=50`).

---

### `job-scraper remote-filter`

Runs the remote-filter agent over all raw jobs and splits them into pass/trash.

```bash
uv run job-scraper remote-filter
```

The legacy script entry point still works:

```bash
python scripts/run_remote_filter.py
```

**Input:** `data/raw/` (all JSONL files)
**Output:** `data/filtered/remote_filter_pass.jsonl`, `data/trash/remote_filter_trash.jsonl`

Agent config is read from `config/agent/remote_agent.yml`. Set `USER_LOCATION` in your `.env` to filter by geography (default: `USA`).

---

## Eval

Eval scripts measure agent accuracy against the human-verified golden dataset and track results across runs. Currently implemented for the remote filter agent. Run records are appended to `data/eval/runs.jsonl` (excluded from git) after every eval.

### `run_remote_filter_eval.py`

Runs the remote filter agent over every record in the golden dataset and writes a durable provenance record to `data/eval/runs.jsonl`.

```bash
uv run scripts/run_remote_filter_eval.py
```

**Input:** `data/eval/ground_truth.jsonl`  
**Output:** `data/eval/runs.jsonl` (appended), `data/eval/mismatches_{run_id}.jsonl` (if any mismatches)

| Flag | Default | Description |
| --- | --- | --- |
| `--gold` | `data/eval/ground_truth.jsonl` | Gold JSONL to evaluate against |
| `--config` | `config/agent/remote_agent.yml` | Agent config YAML |
| `--runs-file` | `data/eval/runs.jsonl` | Run log to append to |
| `--model` | _(from config)_ | Override `llm.model` in-memory — does not modify the YAML |
| `--temperature` | _(from config)_ | Override `llm.temperature` in-memory |
| `--provider` | _(from config)_ | Override `llm.provider` in-memory (`openai` or `ollama`) |
| `--run-id` | _(auto-generated)_ | Human-readable label for this run; rejected if already in `runs.jsonl` |
| `--no-mismatches` | off | Skip writing the mismatch file |
| `--workers` | `1` | Concurrent inference workers. Results are collected in gold-record order and this performance knob is not written to provenance. |

The default provider is `openai` (model: `gpt-4o-mini`) as set in `config/agent/remote_agent.yml`. Use `--provider ollama` to run against a local model instead — no YAML edits needed.

Recent smoke-test baseline on the 104-record gold set:

| run_id | model | workers | accuracy | precision | recall | f1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `smoke_parallel_20260516_045209_a6da` | `gpt-4o-mini` | 4 | 0.8654 | 0.7073 | 0.9355 | 0.8056 |

The current tuning target is reducing false positives: onsite or location-restricted jobs being predicted as pass.

**Examples:**

```bash
# Default run — hits OpenAI API (gpt-4o-mini)
uv run scripts/run_remote_filter_eval.py

# Run against local Ollama instead
# uv run scripts/run_remote_filter_eval.py --provider ollama --model qwen2.5:14b --run-id qwen_14b
uv run scripts/run_remote_filter_eval.py --provider ollama --model qwen25-14b --run-id qwen25_14b_v1

# Try a stronger OpenAI model without editing the YAML
uv run scripts/run_remote_filter_eval.py --model gpt-4o --temperature 0.0 --run-id gpt4o_baseline

# Run synchronous eval with four concurrent workers
uv run scripts/run_remote_filter_eval.py --workers 4 --run-id gpt4o_mini_parallel

# Compare OpenAI vs Ollama results
uv run scripts/compare_evals.py --diff gpt4o_mini_baseline qwen_14b
```

---

### Batch eval — `submit_eval_batch.py` + `poll_eval_batch.py`

For lower-cost regression testing, submit the same gold dataset through the OpenAI Batch API and process it later. Batch eval writes the same `runs.jsonl` schema as synchronous eval, so `compare_evals.py` works unchanged.

```bash
# Submit a batch eval run
uv run python scripts/submit_eval_batch.py --run-id gpt4o_mini_batch

# Later, poll the newest sidecar; exits 0 if the batch is still running
uv run python scripts/poll_eval_batch.py

# Or poll a specific sidecar
uv run python scripts/poll_eval_batch.py --sidecar data/eval/eval_batch_<run_id>.json
```

`submit_eval_batch.py` uses `provider=openai` only. It exits with a clear error for `--provider ollama` because Ollama does not support the OpenAI Batch API.

`poll_eval_batch.py` verifies the gold-file hash before scoring, downloads completed batch results into `data/eval/batch/`, writes mismatch records if needed, and appends the normal eval run record to `data/eval/runs.jsonl`.

---

### `compare_evals.py`

Reads `data/eval/runs.jsonl` and prints a comparison table. Exits cleanly if no runs have been recorded yet.

```bash
uv run scripts/compare_evals.py
```

| Flag | Default | Description |
| --- | --- | --- |
| `--runs-file` | `data/eval/runs.jsonl` | Run log to read |
| `--last N` | _(all)_ | Show only the N most recent runs |
| `--sort-by` | `timestamp` | Sort by `timestamp`, `accuracy`, `precision`, `recall`, or `f1` |
| `--diff <id_a> <id_b>` | — | Side-by-side metric comparison with `↑`/`↓`/`=` indicators |

**Examples:**

```bash
# Show all runs sorted by timestamp
uv run scripts/compare_evals.py

# Show the 5 most recent runs, best F1 first
uv run scripts/compare_evals.py --last 5 --sort-by f1

# Diff two specific runs
uv run scripts/compare_evals.py --diff 20260514_100000_aaaa 20260514_120000_bbbb
```

---

## Data Directory Reference

| Path | Stage | Contents |
|---|---|---|
| `data/raw/` | Bronze | Untouched scraped JSONL from all sources |
| `data/staging/to_review.jsonl` | Silver | Teacher-annotated jobs awaiting human review |
| `data/eval/ground_truth.jsonl` | Gold | Human-verified records from the Streamlit UI |
| `data/filtered/` | — | Student agent pass results |
| `data/trash/` | — | Student agent trash results |
