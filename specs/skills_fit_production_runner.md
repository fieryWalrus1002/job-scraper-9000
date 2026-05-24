# Skills Fit Production Runner (#61)

## Purpose

Close the pipeline after `remote-filter` by adding a production runner that scores live jobs against the candidate profile and writes a ranked shortlist artifact for downstream review and dispatch work.

This spec covers the small focused implementation for GitHub issue #61:

- `scripts/run_skills_fit.py`
- partition-aware input/output resolution
- live-job scoring via existing `skills_fit` agent utilities
- ranked JSONL output under `data/scored/`

This spec does **not** require the broader Phase B follow-ons from `specs/skills_fit_agent_plan.md` such as the `job-scraper skills-fit` CLI subcommand, module README work, or dispatch UI.

---

## Why this spec exists

The repo has already standardized on date-partitioned pipeline stages:

- `data/raw/<DATE>/...`
- `data/prefiltered/<DATE>/remote_filter_input.jsonl`
- `data/local/<DATE>/local_jobs.jsonl`
- `data/filtered/<DATE>/remote_filter_pass.jsonl`

The production skills-fit runner should follow that contract.

Investigation found that the old flat files are no longer meaningful pipeline inputs. Real runs now land in dated partitions, so the production skills-fit runner should require either a `--run-date` or explicit path overrides rather than silently falling back to stale root-level files.

---

## Scope

### In scope

- Add `scripts/run_skills_fit.py`
- Read canonical dated inputs when `--run-date` is provided
- Support explicit path override mode when `--run-date` is omitted
- Score jobs by calling existing `analyze_skills_fit()` only
- Merge remote-filter PASS jobs with local-candidate jobs
- Write ranked JSONL output to `data/scored/`
- Attach per-record provenance metadata
- Log a concise end-of-run summary

### Out of scope

- Changes to `src/agents/skills_fit/`
- Eval harness or gold-set changes
- Review UI / viewer work (#62)
- `job-scraper skills-fit` CLI subcommand
- `src/agents/skills_fit/runner.py` refactor
- RunTracker integration for this component
- `data/runs/<run_id>/...` pipeline professionalization
- Dispatch/email/FastAPI delivery

---

## Canonical pipeline position

```text
data/filtered/<DATE>/remote_filter_pass.jsonl
+ data/local/<DATE>/local_jobs.jsonl
  → scripts/run_skills_fit.py
  → data/scored/<DATE>/skills_fit_scored.jsonl
```

The runner consumes both sources because local jobs are still valid candidates for profile scoring.

---

## Inputs

### Canonical mode

When `--run-date YYYY-MM-DD` is provided, and explicit path overrides are not:

- remote input: `data/filtered/<DATE>/remote_filter_pass.jsonl`
- local input: `data/local/<DATE>/local_jobs.jsonl`
- output: `data/scored/<DATE>/skills_fit_scored.jsonl`

### Explicit override mode

When `--run-date` is omitted, all three path flags must be provided explicitly:

- `--remote-input PATH`
- `--local-input PATH`
- `--output PATH`

If neither `--run-date` nor a full set of explicit path overrides is provided, the runner should fail fast with a clear error.

### Config inputs

- agent config: `config/agent/skills_fit.yml`
- candidate profile: `config/profile/candidate_profile.yml`
- prompt: resolved through the existing `skills_fit` utilities and recorded in provenance

---

## CLI contract

Add a script entrypoint with a minimal CLI:

- `--run-date YYYY-MM-DD`
- `--remote-input PATH`
- `--local-input PATH`
- `--output PATH`
- `--config PATH` (default `config/agent/skills_fit.yml`)
- `--provider VALUE` (optional in-memory override)
- `--model VALUE` (optional in-memory override)
- `--temperature FLOAT` (optional in-memory override)
- `--limit N` (optional, for local testing)

Resolution rules:

1. explicit path flags win
2. otherwise `--run-date` resolves partitioned paths
3. otherwise the runner errors clearly and exits non-zero

---

## Processing rules

### 1. Load config and profile

- Load YAML config from `config/agent/skills_fit.yml`
- Apply any CLI LLM overrides in memory only
- Load candidate profile from the config’s `profile_file` path
- Fail fast if config or profile is missing

### 2. Load job inputs

- Remote input is required
- Local input is optional; if the resolved local file is absent, log that it was not found and continue with remote jobs only
- Read JSONL records from both sources
- Preserve source provenance for each record, e.g. `remote_filter_pass` vs `local_candidate`

### 3. Merge and dedupe

After loading both inputs, merge them into one scoring set.

Deduplicate merged jobs by `dedup_hash`.

Goal: avoid scoring the same job twice if it appears in both streams.

`dedup_hash` is a required upstream pipeline invariant for this runner. Validate it before scoring. If any input record is missing `dedup_hash`, treat that as a run-level input-contract failure: log an error and abort the run rather than inventing fallback identity logic.

### 4. Score with existing agent utility

For each job, call the existing function only:

- `analyze_skills_fit(job_description, candidate_profile=..., title=..., location=..., llm_config=...)`

Do not add new LLM logic in this issue.

### 5. Annotate the job record

Preserve the original job record and enrich it with new fields.

Required fields:

- `_skills_fit_score`
- `_skills_fit_rationale`
- `_skills_fit_hard_concerns`
- `_skills_fit_top_matches`
- `_skills_fit_metadata`

Recommended additional fields for downstream usefulness:

- `_skills_fit_analysis` — full structured analysis payload
- `_skills_fit_gaps`
- `_skills_fit_confidence`
- `_skills_fit_input_source` — `remote_filter_pass` or `local_candidate`

### 6. Sort output

Sort final output before writing:

1. successfully scored records before failed/unscored records
2. `_skills_fit_score` descending
3. `dedup_hash` ascending

This makes ties deterministic across runs. `dedup_hash` is required on all input records, so the runner should validate that invariant before scoring begins.

### 7. Write output

- Create parent directories as needed
- Write JSONL to the resolved output path
- Overwrite the output file for a fresh run

---

## Failure behavior

### Fail fast

Exit non-zero if:

- config file is missing
- profile file is missing
- remote input file is missing
- prompt file resolution fails
- any input record is missing `dedup_hash`

### Per-record non-fatal failures

Do not abort the whole run for one bad record.

Cases:

- missing description
- agent returns `None`

Behavior:

- `log.warning(...)`
- keep the record in output
- set score-derived fields to `null` or empty lists as appropriate
- record failure reason in `_skills_fit_metadata`

This keeps the output auditable for record-level scoring failures without hiding upstream pipeline-shape problems.

---

## Provenance contract

Each output record must carry enough metadata to compare runs safely.

`_skills_fit_metadata` should include at least:

- `run_id`
- `scored_at`
- `config_file`
- `prompt_file`
- `prompt_hash`
- `profile_file`
- `profile_hash`
- `profile_version`
- `provider`
- `model`
- `temperature`
- `skills_fit_schema_version`
- `commit`
- `dirty`
- `input_source`
- `input_path`
- optional `failure_reason` when the record was not scored

The metadata contract should follow existing provenance patterns from:

- `scripts/run_skills_fit_eval.py`
- other shared provenance helpers already present in the repo

---

## Output contract

Canonical output path:

- `data/scored/<DATE>/skills_fit_scored.jsonl`

Explicit override output path:

- whatever `--output PATH` resolves to

Output record shape is:

- original input job fields
- original upstream annotations (`_remote_analysis`, `_filter_metadata`, etc.) preserved
- new `_skills_fit_*` annotations added by this runner

---

## Logging / summary

The script should log enough to verify the run without opening the whole file.

Recommended summary counters:

- remote records loaded
- local records loaded
- merged records before dedupe
- merged records after dedupe
- scored successfully
- skipped missing description
- failed agent
- output path written

A short preview of the top-ranked jobs is nice to have but not required for #61.

---

## Acceptance criteria

- `uv run scripts/run_skills_fit.py --run-date <DATE>` succeeds against a real dated partition
- default canonical input resolution uses dated directories
- the runner fails clearly when neither `--run-date` nor full explicit path overrides are provided
- explicit path override mode works when `--run-date` is omitted
- output is written to `data/scored/<DATE>/skills_fit_scored.jsonl` in canonical mode
- output records are ranked by descending `_skills_fit_score`
- output records include the required `_skills_fit_*` fields
- output records include `profile_hash` and `profile_version`
- local jobs are included when the dated `data/local/<DATE>/local_jobs.jsonl` exists
- duplicate jobs across remote/local inputs are not scored twice when they share `dedup_hash`
- equal-score jobs are ordered deterministically by `dedup_hash`
- the run aborts with a clear error if any input record is missing `dedup_hash`

---

## Notes for future follow-on work

This issue is intentionally smaller than the full productionization described elsewhere.

Likely later follow-ons:

- `src/agents/skills_fit/runner.py`
- `job-scraper skills-fit --run-date <DATE>` CLI subcommand
- results viewer / shortlist UI (#62)
- RunTracker integration; until then, skills-fit runs and costs will not appear in `data/runs/runs.jsonl`
- skills-fit analysis caching, likely via a shared generic analysis-cache base rather than a one-off implementation
- append-only run manifests under `data/runs/` or `data/runs/<run_id>/...`
- broader pipeline professionalization around run manifests / component orchestration
