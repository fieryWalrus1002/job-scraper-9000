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

______________________________________________________________________

## Scripts

### `push_user_config.py` / `pull_user_configs.py`

Admin CLI for the per-user configs that live in Postgres (Phase 12, [specs/configs_in_db_design.md](../specs/configs_in_db_design.md)). Both connect to the DB directly via `DATABASE_URL`; no API involvement.

`push_user_config.py` validates a filled-in profile/search template against the shared Pydantic models (`src/user_config/`) and upserts it for a user, printing the computed `profile_version`. Use it to onboard a user before they've touched the in-app Settings form. The user must already exist in `app.users`.

```bash
uv run scripts/push_user_config.py --user-email a@b.com \
    --profile config/profile/alice.yml --search config/search/alice.yml
```

`pull_user_configs.py` materializes the DB back to the YAML the pipeline consumes — `runs/<email-slug>/{search.yml,candidate_profile.yml,policies.yml}` — so an overnight run can pick it up.

```bash
uv run scripts/pull_user_configs.py --all          # every configured user
uv run scripts/pull_user_configs.py --user-email a@b.com
```

______________________________________________________________________

### `prepare_batch.py`

Reads raw jobs and produces an [OpenAI Batch API](https://platform.openai.com/docs/guides/batch) request file.

```bash
python scripts/prepare_batch.py
```

**Input:** `data/raw/scraped_jobs.jsonl`
**Output:** `data/raw/gpt_teacher_batch.jsonl`

After running, upload the output file to the OpenAI Batch API dashboard (or via API), wait for completion, and download the results file.

______________________________________________________________________

### `merge_batch_results.py`

Joins the downloaded OpenAI batch results back onto the original job records and writes the merged staging file that the review UI reads.

```bash
python scripts/merge_batch_results.py \
    --jobs    data/raw/scraped_jobs.jsonl \
    --results data/raw/gpt_teacher_results.jsonl \
    --output  data/staging/to_review.jsonl
```

| Flag        | Default                              | Description                                  |
| ----------- | ------------------------------------ | -------------------------------------------- |
| `--jobs`    | `data/raw/scraped_jobs.jsonl`        | Original jobs file fed to `prepare_batch.py` |
| `--results` | `data/raw/gpt_teacher_results.jsonl` | Downloaded batch results from OpenAI         |
| `--output`  | `data/staging/to_review.jsonl`       | Merged output for the review UI              |
| `--append`  | off                                  | Append to output instead of overwriting      |

Items where the batch API returned an error are logged and skipped.

______________________________________________________________________

### `sample_for_review.py`

Pulls a random sample of raw job records into staging. Useful for spot-checking data quality without running the full teacher pipeline.

```bash
python scripts/sample_for_review.py
```

**Input:** `data/raw/pass.jsonl`
**Output:** `data/staging/review_batch.jsonl`

Edit `create_sample_batch()` arguments directly to change the source file or sample size (default `n=50`).

______________________________________________________________________

### `job-scraper-9000 remote-filter`

Runs the remote-filter agent over routed candidate jobs and writes profile-independent classification output.

```bash
uv run job-scraper-9000 remote-filter
```

The legacy script entry point still works:

```bash
uv run scripts/run_remote_filter.py
```

**Input:** `data/prefiltered/remote_filter_input.jsonl`
**Output:** `data/filtered/remote_filter_classified.jsonl`

Agent LLM config is read from `config/agent/remote_agent.yml`. Accept/reject policy is per-user and runs later in the scoring stage.

______________________________________________________________________

## Eval

Eval scripts measure agent accuracy against the human-verified golden dataset and track results across runs. Currently implemented for the remote filter agent. Run records are appended to `data/eval/runs.jsonl` (excluded from git) after every eval.

### `run_remote_filter_eval.py`

Runs the remote filter agent over every record in the golden dataset and writes a durable provenance record to `data/eval/runs.jsonl`.

```bash
uv run scripts/run_remote_filter_eval.py
```

**Input:** `data/eval/ground_truth.jsonl`
**Output:** `data/eval/runs.jsonl` (appended), `data/eval/mismatches_{run_id}.jsonl` (if any mismatches)

| Flag              | Default                         | Description                                                                                                                      |
| ----------------- | ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `--gold`          | `data/eval/ground_truth.jsonl`  | Gold JSONL to evaluate against                                                                                                   |
| `--config`        | `config/agent/remote_agent.yml` | Agent config YAML                                                                                                                |
| `--runs-file`     | `data/eval/runs.jsonl`          | Run log to append to                                                                                                             |
| `--model`         | _(from config)_                 | Override `llm.model` in-memory — does not modify the YAML                                                                        |
| `--temperature`   | _(from config)_                 | Override `llm.temperature` in-memory                                                                                             |
| `--provider`      | _(from config)_                 | Override `llm.provider` in-memory (`openai` or `ollama`)                                                                         |
| `--run-id`        | _(auto-generated)_              | Human-readable label prefix; a timestamp + random suffix are always appended to keep run IDs unique.                             |
| `--no-mismatches` | off                             | Skip writing the mismatch file                                                                                                   |
| `--workers`       | `1`                             | Concurrent inference workers. Results are collected in gold-record order and this performance knob is not written to provenance. |

The default provider is `openai` (model: `gpt-4o-mini`) as set in `config/agent/remote_agent.yml`. Use `--provider ollama` to run against a local model instead — no YAML edits needed.

The remote-filter eval reports the native 4-way classification metric (`remote`, `hybrid`, `onsite`, `unclear`) with confusion matrix, per-class precision/recall/F1, macro/micro scores, and travel-days MAE.

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

______________________________________________________________________

### `compare_evals.py`

Reads `data/eval/runs.jsonl` and prints a comparison table. Exits cleanly if no runs have been recorded yet.

```bash
uv run scripts/compare_evals.py
```

| Flag                          | Default                | Description                                                                 |
| ----------------------------- | ---------------------- | --------------------------------------------------------------------------- |
| `--runs-file`                 | `data/eval/runs.jsonl` | Run log to read                                                             |
| `--last N`                    | _(all)_                | Show only the N most recent runs                                            |
| `--sort-by`                   | `timestamp`            | Sort by `timestamp` or a scorer-specific metric                             |
| `--diff <id_a> <id_b>`        | —                      | Side-by-side metric comparison with `↑`/`↓`/`=` indicators                  |
| `--against-champion <scorer>` | —                      | Resolve the left-hand diff run from `config/eval/champions.yml`             |
| `--per-record`                | `false`                | After aggregate diff, print a per-record markdown table (`skills_fit` only) |

**Examples:**

```bash
# Show all runs sorted by timestamp
uv run scripts/compare_evals.py

# Show the 5 most recent runs, best F1 first
uv run scripts/compare_evals.py --last 5 --sort-by f1

# Diff two specific runs
uv run scripts/compare_evals.py --diff 20260514_100000_aaaa 20260514_120000_bbbb

# Compare a new skills_fit run against the pinned champion
uv run scripts/compare_evals.py \
  --against-champion skills_fit \
  --diff phase_g_pr1_llm_reframe_v5_20260523_182056_fbf3 \
  --per-record
```

______________________________________________________________________

## Data Directory Reference

| Path                           | Stage  | Contents                                     |
| ------------------------------ | ------ | -------------------------------------------- |
| `data/raw/`                    | Bronze | Untouched scraped JSONL from all sources     |
| `data/staging/to_review.jsonl` | Silver | Teacher-annotated jobs awaiting human review |
| `data/eval/ground_truth.jsonl` | Gold   | Human-verified records from the Streamlit UI |
| `data/filtered/`               | —      | Student agent pass results                   |
| `data/trash/`                  | —      | Student agent trash results                  |

______________________________________________________________________

## skills_fit — seed gold + eval workflow

Phase 3 (Skills Fit) scores remote-filter PASS jobs against the versioned candidate profile at `config/profile/candidate_profile.yml`. The seed gold set is built teacher-first: a frontier LLM proposes labels, a human reviews them in markdown, and the parsed result becomes `data/eval/skills_fit_ground_truth.jsonl`.

See [src/agents/skills_fit/README.md](../src/agents/skills_fit/README.md) for the agent overview and [specs/skills_fit_agent_plan.md](../specs/skills_fit_agent_plan.md) for the full Phase R / G / B plan.

### Pipeline overview

```text
data/filtered/                                      ← remote-filter PASS records
    │
    ├─ prepare_skills_fit_seed.py                   → data/staging/skills_fit_seed_template.jsonl
    │
    ├─ propose_skills_fit_seed.py (teacher LLM)     → data/staging/skills_fit_seed_proposed.jsonl
    │
    ├─ render_skills_fit_review_md.py               → data/staging/skills_fit_review/*.md
    │       [human ratifies / overrides / skips in the markdown files]
    ├─ parse_skills_fit_review_md.py                → data/eval/skills_fit_ground_truth.jsonl  (Gold)
    │
    └─ run_skills_fit_eval.py                       → data/eval/runs.jsonl
```

`score_skills_fit_seed.py` is an alternative CLI-driven review loop kept around for headless / non-markdown reviewing; both paths write the same gold JSONL.

### `prepare_skills_fit_seed.py`

Samples remote-filter PASS records into a blank seed template for hand-scoring.

```bash
uv run scripts/prepare_skills_fit_seed.py --n 40 --in data/filtered/
```

**Output:** `data/staging/skills_fit_seed_template.jsonl` with empty `_human_*` fields.

### `propose_skills_fit_seed.py`

Teacher LLM proposes labels and rationale for every template record. Calls `load_dotenv()`, so `OPENAI_API_KEY` from `.env` is picked up. Resume-safe by `source_job_id`.

```bash
uv run scripts/propose_skills_fit_seed.py --model gpt-5.5 --temperature 1.0
```

| Flag            | Default                                       | Description                                                         |
| --------------- | --------------------------------------------- | ------------------------------------------------------------------- |
| `--in`          | `data/staging/skills_fit_seed_template.jsonl` | Template produced by `prepare_skills_fit_seed.py`                   |
| `--out`         | `data/staging/skills_fit_seed_proposed.jsonl` | Proposed-label output (appended, resume-safe)                       |
| `--config`      | `config/agent/skills_fit.yml`                 | Agent config (provides default LLM block)                           |
| `--model`       | _(from config)_                               | Override the model                                                  |
| `--temperature` | _(from config)_                               | Override the temperature (ignored by reasoning models that lock it) |
| `--prompt`      | _(skills-fit prompt)_                         | Override the system prompt file                                     |
| `--limit`       | _(all)_                                       | Cap the number of records (smoke testing)                           |

**Note on `gpt-5.5`:** the GPT-5 family rejects custom `temperature` and runs at its default (1.0). The flag is accepted but the API may ignore it for those models.

### `render_skills_fit_review_md.py`

Renders proposed records as one markdown file per posting, with teacher labels visible and editable fields for the human reviewer.

```bash
uv run scripts/render_skills_fit_review_md.py
```

**Output:** `data/staging/skills_fit_review/<idx>_<source_job_id>_<slug>.md`

### `parse_skills_fit_review_md.py`

Parses the filled-in markdown files back into gold JSONL. Preserves `_teacher_*` fields alongside `_human_*` labels for audit trail.

```bash
uv run scripts/parse_skills_fit_review_md.py
```

**Output:** `data/eval/skills_fit_ground_truth.jsonl` (append-only; last entry per `dedup_hash` wins).

### `score_skills_fit_seed.py`

Headless CLI alternative to the markdown review. Auto-detects the proposed file: when present, shows teacher labels and prompts `a` accept / `1-5` override / `s` skip / `q` quit, with press-enter-to-keep defaults on list fields. `_human_notes` is mandatory on every saved record.

```bash
uv run scripts/score_skills_fit_seed.py
```

**Output:** `data/eval/skills_fit_ground_truth.jsonl` (same gold file as the markdown path).

### `run_skills_fit_eval.py`

Loads the gold set, runs either the LLM scorer (`analyze_skills_fit`) or the keyword baseline (`keyword_overlap_analyze`), computes ordinal + top-k metrics, and writes a `runs.jsonl` record with full provenance (prompt hash, profile hash, `profile_version`, git commit, scorer choice, metric set).

Also snapshots the in-flight candidate profile to `config/profile/old_profiles/candidate_profile_<profile_version>.yml` on every run (idempotent — re-runs against the same `profile_version` are no-ops). The directory is gitignored because profiles contain PII.

```bash
uv run scripts/run_skills_fit_eval.py --scorer keyword --run-id phase_r_keyword
uv run scripts/run_skills_fit_eval.py --scorer llm     --run-id phase_r_llm_rubric
```

| Flag                                       | Default                                   | Description                                                                                          |
| ------------------------------------------ | ----------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `--gold`                                   | `data/eval/skills_fit_ground_truth.jsonl` | Gold JSONL to evaluate against                                                                       |
| `--config`                                 | `config/agent/skills_fit.yml`             | Agent config YAML                                                                                    |
| `--scorer`                                 | `llm`                                     | `llm` or `keyword`                                                                                   |
| `--model` / `--provider` / `--temperature` | _(from config)_                           | In-memory overrides                                                                                  |
| `--run-id`                                 | _(auto-generated)_                        | Human-readable label prefix; a timestamp + random suffix are always appended to keep run IDs unique. |
| `--workers`                                | `1`                                       | Concurrent inference workers for the LLM scorer                                                      |
| `--no-mismatches`                          | off                                       | Skip writing the mismatch file                                                                       |

### Re-running after a profile bump

Profile changes invalidate existing teacher proposals (they were scored against a different contract). To refresh the seed pool:

```bash
rm data/staging/skills_fit_seed_proposed.jsonl
rm -rf data/staging/skills_fit_review/
uv run scripts/propose_skills_fit_seed.py --model gpt-5.5 --temperature 1.0
uv run scripts/render_skills_fit_review_md.py
```
