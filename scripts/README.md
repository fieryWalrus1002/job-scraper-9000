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

### `run_remote_filter.py`

Runs the local student agent (`remote_filter`) over all raw jobs and splits them into pass/trash. This is the production inference path — no cloud API calls.

```bash
python scripts/run_remote_filter.py
```

**Input:** `data/raw/` (all JSONL files)
**Output:** `data/filtered/remote_filter_pass.jsonl`, `data/trash/remote_filter_trash.jsonl`

Agent config is read from `config/agent/remote_agent.yml`. Set `USER_LOCATION` in your `.env` to filter by geography (default: `USA`).

---

## Data Directory Reference

| Path | Stage | Contents |
|---|---|---|
| `data/raw/` | Bronze | Untouched scraped JSONL from all sources |
| `data/staging/to_review.jsonl` | Silver | Teacher-annotated jobs awaiting human review |
| `data/eval/ground_truth.jsonl` | Gold | Human-verified records from the Streamlit UI |
| `data/filtered/` | — | Student agent pass results |
| `data/trash/` | — | Student agent trash results |
