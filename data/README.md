# `data/` — directory layout and writers

This repo treats `data/` as the local pipeline workspace. Most JSONL contents are gitignored; `.gitkeep` files preserve empty directories. This document summarizes what each folder is for and which code paths create, overwrite, or append files under it.

## Summary by folder

| Folder | Writers / processes | Default outputs |
|---|---|---|
| `data/raw/` | `job-scraper <scraper> --save`; `job-scraper run-config --save` | Flat: `data/raw/YYYY-MM-DD_HH-MM_<source>_<keywords>.jsonl`; with `run-config --run-date`: `data/raw/YYYY-MM-DD/*.jsonl` |
| `data/prefiltered/` | `job-scraper prefilter` via `src/prefilter/router.py` | `data/prefiltered/remote_filter_input.jsonl` or `data/prefiltered/<date>/remote_filter_input.jsonl`; overwritten |
| `data/local/` | `job-scraper prefilter` via `src/prefilter/router.py` | `data/local/local_jobs.jsonl` or `data/local/<date>/local_jobs.jsonl`; overwritten |
| `data/trash/` | `job-scraper prefilter`; `job-scraper remote-filter` | `prefilter_trash.jsonl` and `remote_filter_trash.jsonl`; overwritten |
| `data/filtered/` | `job-scraper remote-filter` via `src/agents/remote_filter/runner.py` | `data/filtered/remote_filter_pass.jsonl` or `data/filtered/<date>/remote_filter_pass.jsonl`; overwritten |
| `data/cache/` | Remote filter analysis cache via `src/agents/remote_filter/cache.py` | `data/cache/remote_filter_analyses.jsonl`; append-only unless `--no-cache` is used |
| `data/batch/` | `scripts/prepare_batch.py`; `scripts/submit_batch.py` | `gpt_teacher_batch.jsonl`, `gpt_teacher_jobs.jsonl`, `last_batch_id.txt`, `gpt_teacher_results.jsonl` under `data/batch/<date>/` |
| `data/staging/` | `scripts/merge_batch_results.py`; skills-fit seed/review scripts; `scripts/sample_for_review.py` | `to_review.jsonl` append; `skills_fit_seed_template.jsonl` overwrite; `skills_fit_seed_proposed.jsonl` append; `skills_fit_review/*.md` write; `review_batch.jsonl` overwrite |
| `data/eval/` | Streamlit review UI; eval runners; eval batch scripts; skills-fit gold parsers/scorer | `ground_truth.jsonl` append; `skills_fit_ground_truth.jsonl` append; `runs.jsonl` append; `mismatches_<run_id>.jsonl` overwrite; `eval_batch_<run_id>.json`; `batch/eval_requests/results/errors_*.jsonl` |
| `data/archive/` | No implemented repo writer found | Current contents appear manually archived, likely from `data/staging/skills_fit_review/` |
| `data/runs/` | `RunTracker` (`src/utils/run_tracker.py`) — wrapping every pipeline component run | `data/runs/runs.jsonl`; append-only |

`data/scored/` is documented separately under "Planned but not yet implemented" below.

## Details and code evidence

### `data/raw/`

**Purpose:** Bronze layer — immutable source-of-truth scrape outputs from all scrapers. Partitioned by `--run-date` when used; otherwise flat.

Scraper CLI output is rooted at `DATA_DIR = Path("data/raw")` in `src/job_scraper/cli.py`.

- `job-scraper linkedin ... --save`, `job-scraper jobspy ... --save`, `job-scraper sel ... --save`, etc. write JSONL via `_output()`.
- `job-scraper run-config config/search.yml --save` writes one file per scraper as each scraper completes.
- `job-scraper run-config ... --run-date YYYY-MM-DD --save` partitions output under `data/raw/YYYY-MM-DD/`.

Evidence:

- `src/job_scraper/cli.py:18` defines `DATA_DIR = Path("data/raw")`.
- `src/job_scraper/cli.py:38-39` builds flat or date-partitioned auto paths.
- `src/job_scraper/cli.py:47` creates the parent directory.
- `src/job_scraper/cli.py:55` writes JSONL with `open(dest, "w")`.
- `src/job_scraper/cli.py:658` creates per-scraper destination parents in `run-config`.

### `data/prefiltered/`, `data/local/`, and prefilter `data/trash/`

**Purpose:** Deterministic prefilter outputs. `prefiltered/` holds candidates routed for remote-fit LLM evaluation; `local/` holds candidates kept aside as local opportunities (Pullman/Moscow area); `trash/` holds explicit rejects (non-US, clearly non-viable, etc.).

The deterministic prefilter routes raw jobs into three buckets:

- Remote-filter candidates → `data/prefiltered/.../remote_filter_input.jsonl`
- Local candidates → `data/local/.../local_jobs.jsonl`
- Prefilter rejects → `data/trash/.../prefilter_trash.jsonl`

Default paths are flat unless `--run-date YYYY-MM-DD` is used.

Evidence:

- `src/job_scraper/cli.py:431-439` resolves `job-scraper prefilter` paths, including date partitions.
- `src/prefilter/router.py:30-33` defines default input/output paths.
- `src/prefilter/router.py:456-458` creates output directories.
- `src/prefilter/router.py:462-475` opens all three outputs in write mode and writes routed JSONL records.

### `data/filtered/` and remote-filter `data/trash/`

**Purpose:** Remote-filter LLM pass/trash split for jobs routed through the remote stream. `filtered/` holds genuinely remote-flexible postings; `trash/` holds onsite-disguised, hybrid-required, US-only-mismatch, etc.

The remote filter consumes routed candidates and splits them into pass/trash outputs:

- Pass → `data/filtered/.../remote_filter_pass.jsonl`
- Trash → `data/trash/.../remote_filter_trash.jsonl`

Default paths are flat unless `--run-date YYYY-MM-DD` is used.

Evidence:

- `src/job_scraper/cli.py:511-517` resolves `job-scraper remote-filter` paths.
- `src/agents/remote_filter/runner.py:24-26` defines default input/pass/trash paths.
- `src/agents/remote_filter/runner.py:104-111` creates parent directories and opens pass/trash outputs in write mode.
- `src/agents/remote_filter/runner.py:182` writes passing records.
- `src/agents/remote_filter/runner.py:192` writes rejected records.

### `data/cache/`

**Purpose:** Append-only analysis cache for remote_filter. Lets re-runs skip LLM calls for already-classified `(dedup_hash, prompt_hash, model)` triples. Prompt or model changes naturally invalidate via the composite key.

The remote filter uses an append-only analysis cache unless disabled with `--no-cache`.

Evidence:

- `src/job_scraper/cli.py:519-521` sets cache path from `--cache-path`, `--no-cache`, or default.
- `src/agents/remote_filter/cache.py:15` defines `DEFAULT_CACHE_PATH = Path("data/cache/remote_filter_analyses.jsonl")`.
- `src/agents/remote_filter/cache.py:113-114` creates the parent and appends JSONL cache entries.
- `src/agents/remote_filter/runner.py:162` calls `cache.put(...)` after a successful uncached analysis.

### `data/batch/`

**Purpose:** OpenAI Batch API artifacts for the teacher pipeline. Request files, batch IDs, downloaded results, and sidecar metadata — organized per-run-date.

The teacher batch pipeline stores OpenAI Batch API request/sidecar/result files under a run directory, defaulting to `data/batch/<today>/`.

Writers:

- `scripts/prepare_batch.py`
  - Writes `gpt_teacher_batch.jsonl`.
  - Writes `gpt_teacher_jobs.jsonl`.
- `scripts/submit_batch.py`
  - Writes `last_batch_id.txt` after upload.
  - Writes `gpt_teacher_results.jsonl` after download.

Evidence:

- `scripts/prepare_batch.py:33-34` sets `INPUT_DIR = "data/raw"` and `DEFAULT_RUN_DIR = f"data/batch/{date.today().isoformat()}"`.
- `scripts/prepare_batch.py:103-107` creates the run directory and opens sidecar/batch files in write mode.
- `scripts/submit_batch.py:32` sets the same default run directory pattern.
- `scripts/submit_batch.py:77` writes `last_batch_id.txt`.
- `scripts/submit_batch.py:117` writes downloaded batch results.

### `data/staging/`

**Purpose:** Silver layer — teacher-annotated and review-in-progress artifacts that haven't yet become gold. Includes the skills_fit teacher proposals and per-record markdown review files awaiting human ratification.

Staging holds teacher-annotated review inputs and skills-fit review artifacts.

Writers:

- `scripts/merge_batch_results.py`
  - Appends merged teacher results to `data/staging/to_review.jsonl`.
- `scripts/prepare_skills_fit_seed.py`
  - Overwrites `data/staging/skills_fit_seed_template.jsonl`.
- `scripts/propose_skills_fit_seed.py`
  - Appends proposals to `data/staging/skills_fit_seed_proposed.jsonl`.
- `scripts/render_skills_fit_review_md.py`
  - Writes Markdown review files under `data/staging/skills_fit_review/`; skips existing files unless `--overwrite` is passed.
- `scripts/sample_for_review.py`
  - Writes `data/staging/review_batch.jsonl` in its default example path.

Evidence:

- `scripts/merge_batch_results.py:31-32` defines the default batch run dir and staging file.
- `scripts/merge_batch_results.py:89` creates the staging parent.
- `scripts/merge_batch_results.py:111` appends to staging.
- `scripts/prepare_skills_fit_seed.py:23` defines `DEFAULT_OUT = Path("data/staging/skills_fit_seed_template.jsonl")`.
- `scripts/prepare_skills_fit_seed.py:76-77` creates parent and writes the template in write mode.
- `scripts/propose_skills_fit_seed.py:36-37` defines default template/proposed paths.
- `scripts/propose_skills_fit_seed.py:54-55` appends proposed records.
- `scripts/render_skills_fit_review_md.py:32-35` defines default template/proposed/gold/review-dir paths.
- `scripts/render_skills_fit_review_md.py:232` creates the output directory.
- `scripts/render_skills_fit_review_md.py:247` writes each Markdown review file.
- `scripts/sample_for_review.py:19` writes sampled JSONL with `to_json(...)`.
- `scripts/sample_for_review.py:25` uses the default example target `data/staging/review_batch.jsonl`.

### `data/eval/`

**Purpose:** Gold layer — human-verified ground-truth labels for each agent, eval run metadata (`runs.jsonl`), mismatch logs for debugging, and OpenAI Batch API artifacts for eval-time inference.

Eval data includes human gold sets, run logs, mismatches, and batch eval request/result artifacts.

Writers:

- `src/review_ui/app.py`
  - Appends human remote-filter labels to `data/eval/ground_truth.jsonl`.
- `scripts/score_skills_fit_seed.py`
  - Appends human skills-fit labels to `data/eval/skills_fit_ground_truth.jsonl`.
- `scripts/parse_skills_fit_review_md.py`
  - Appends parsed Markdown review labels to `data/eval/skills_fit_ground_truth.jsonl`.
- `scripts/run_remote_filter_eval.py`
  - Writes `data/eval/mismatches_<run_id>.jsonl` when mismatches exist.
  - Appends run metadata through `JsonlRunLogger`, defaulting to `data/eval/runs.jsonl`.
- `scripts/run_skills_fit_eval.py`
  - Writes `data/eval/mismatches_<run_id>.jsonl` when mismatches exist.
  - Appends run metadata through `JsonlRunLogger`, defaulting to `data/eval/runs.jsonl`.
- `scripts/submit_eval_batch.py`
  - Writes `data/eval/batch/eval_requests_<run_id>.jsonl`.
  - Writes `data/eval/eval_batch_<run_id>.json` sidecars.
- `scripts/poll_eval_batch.py`
  - Downloads `data/eval/batch/eval_results_<run_id>.jsonl`.
  - May download `data/eval/batch/eval_errors_<run_id>.jsonl`.
  - Updates the sidecar JSON with result metadata.
  - Writes `data/eval/mismatches_<run_id>.jsonl`.
  - Appends run metadata to `data/eval/runs.jsonl`.

Evidence:

- `src/review_ui/app.py:16-17` defines staging/eval paths.
- `src/review_ui/app.py:91` creates the eval directory.
- `src/review_ui/app.py:101` appends to `ground_truth.jsonl`.
- `scripts/score_skills_fit_seed.py:35-37` defines skills-fit template/proposed/gold defaults.
- `scripts/score_skills_fit_seed.py:68-69` appends skills-fit gold records.
- `scripts/parse_skills_fit_review_md.py:31-34` defines defaults including `DEFAULT_GOLD`.
- `scripts/parse_skills_fit_review_md.py:70-71` appends parsed records.
- `scripts/run_remote_filter_eval.py:45-47` defines gold and runs defaults.
- `scripts/run_remote_filter_eval.py:367-369` writes remote-filter mismatch files.
- `scripts/run_skills_fit_eval.py:50-52` defines skills-fit gold and runs defaults.
- `scripts/run_skills_fit_eval.py:374-376` writes skills-fit mismatch files.
- `src/agent_eval/logger.py:39` defaults `JsonlRunLogger` to `data/eval/runs.jsonl`.
- `src/agent_eval/logger.py:76-78` creates parent and appends run records.
- `scripts/submit_eval_batch.py:39-40` defines default eval batch and sidecar dirs.
- `scripts/submit_eval_batch.py:167-169` writes batch eval requests.
- `scripts/submit_eval_batch.py:268-269` writes eval batch sidecars.
- `scripts/poll_eval_batch.py:91-114` downloads results and updates sidecar metadata.
- `scripts/poll_eval_batch.py:302` constructs the eval error-file path.
- `scripts/poll_eval_batch.py:326-328` writes mismatch files.

### `data/archive/`

**Purpose:** Manually archived snapshots of staging artifacts. No automated writer — populated ad-hoc when an older snapshot needs preservation (e.g., archiving a v3-profile-era review batch before re-proposing against v4).

No implemented repo writer was found for `data/archive/`. Existing files under `data/archive/skills_fit_review_v3_20260521/` look like manually archived Markdown review artifacts, likely copied or moved from `data/staging/skills_fit_review/` outside the tracked scripts.

### `data/runs/`

**Purpose:** Per-run telemetry — one structured record per pipeline component invocation (scraper, prefilter, remote_filter, skills_fit, eval). Captures timing, input/output counts, git provenance, LLM model + token usage + cost estimate, cache stats, rate-limit events, and parent-run linkage.

Append-only JSONL at `data/runs/runs.jsonl`. Written by the `RunTracker` context manager in `src/utils/run_tracker.py`; each pipeline component wraps its work in a `with RunTracker(component="...") as run:` block. Cost reconciliation against OpenAI's authoritative numbers is handled by `scripts/sync_openai_costs.py`, which queries the OpenAI Costs API (requires `OPENAI_ADMIN_KEY`) and back-fills the `cost.actual_provider_total` field.

Query examples:

```bash
# Today's total estimated cost by component
jq -s 'map(select(.timing.started_at | startswith("2026-05-21"))) | group_by(.component) | map({component: .[0].component, cost: (map(.cost.estimated_total // 0) | add)})' data/runs/runs.jsonl

# Median per-record cost for remote_filter, grouped by model
jq -s 'map(select(.component == "remote_filter" and .cost != null)) | group_by(.llm.model) | map({model: .[0].llm.model, median: ([.[].cost.estimated_per_record] | sort | .[length/2])})' data/runs/runs.jsonl
```

## Planned but not yet implemented

### `data/scored/`

**Purpose (planned):** Skills_fit production-runner output. Will hold per-job 1-5 ordinal fit scores, rationale, and matching evidence — the dispatch-ready output that drives the daily shortlist.

**Status:** No writer implemented. Mentioned in specs as the planned skills_fit production output path, e.g. `data/scored/<DATE>/skills_fit_scored.jsonl`. Will land with Phase B of the skills_fit agent plan.

## Notes

- I did not find implemented repo code that renames, moves, or deletes files under `data/`.
- Tests generally write to `tmp_path`, not the real `data/` tree.
- `.gitignore` ignores `data/**/*.jsonl`, `data/**/*.txt`, and `data/**/*.md`, so most generated data artifacts remain local.
