# remote-filter

A structured-output LLM agent that reads job descriptions and classifies their remote-work policy. It catches issues that keyword filters miss: travel requirements, local presence clauses, relocation language, hard timezone constraints, and location restrictions disguised as remote roles.

______________________________________________________________________

## Configuration

Runtime policy lives in [`config/agent/remote_agent.yml`](../../../config/agent/remote_agent.yml). The active system prompt lives separately at:

```text
prompts/remote_agent/system_prompt.txt
```

Historical prompt copies are under:

```text
prompts/remote_agent/versions/
```

The eval framework records the resolved prompt hash, config, git metadata, and dataset hash for each run.

Current config shape:

```yaml
llm:
  provider: ollama        # openai | ollama (the ollama provider also targets
  model: qwen-27b-mtp     # llama.cpp via its OpenAI-compatible API)
  temperature: 0.1
  base_url: http://localhost:8080/v1   # llama.cpp default; Ollama's is 11434

policy_thresholds:
  disallowed_classifications:
    - "onsite_disguised"
    - "hybrid"
    # location_restricted is handled by the geographic/timezone checks below.

  travel:
    # Sole travel gate as of SCHEMA_VERSION 3.0.0 — the old per-category
    # remote_with_*_travel buckets were dropped; travel is judged on the
    # numeric estimate the model emits.
    max_estimated_days_per_year: 15

  relocation:
    # Permissive at the global/consolidation layer. Relocation and local
    # presence are per-user preferences, so they are gated per user in
    # pipeline.scoring.score_run (from the stored UserPolicies), not here — the
    # global pool stays maximally inclusive. See specs/relocation_policy.md §2.1.
    allow_required_relocation: true
    allow_local_presence_required: true

  uncertainty:
    on_unclear_classification: "reject"

  timezone:
    user_timezone: "PST"
    rejected_timezone_keywords:
      - "EST"
      - "ET"
      - "Eastern"
      - "Eastern time"
      - "Eastern Standard Time"
```

To retune behavior, adjust `policy_thresholds` or the prompt and rerun evals.

______________________________________________________________________

## Running the agent

The CLI reads the routed candidate JSONL from `data/prefiltered/remote_filter_input.jsonl` by default, applies the remote filter, and writes pass/trash outputs:

```bash
uv run job-scraper-9000 remote-filter
```

The legacy script entry point still works:

```bash
python scripts/run_remote_filter.py
```

Outputs:

- `data/filtered/remote_filter_pass.jsonl`
- `data/trash/remote_filter_trash.jsonl`

Override `--input data/raw` if you want to run the filter directly on raw scraped jobs.

Within-batch duplicates (by `dedup_hash`, falling back to `source_job_id`) are collapsed before the LLM step — when the same posting shows up in multiple scrapers in one run, it's analyzed once.

Across-batch analyses are cached at `data/cache/remote_filter_analyses.jsonl`, keyed by `(dedup_hash, prompt_hash, provider, model, context_fp)` — where `dedup_hash` falls back to `source_job_id` when absent, and `context_fp` is a fingerprint of the search-context fields the prompt actually reads (`keywords`, `workplace`, `job_type`, `user_timezone`). Any of: a prompt edit, a model or provider swap, or a change to a context field that affects the prompt → key changes → cache misses and recomputes. No manual invalidation needed. Pass `--no-cache` to bypass, or `--cache-path` to point elsewhere. The run summary logs `cache N/M hits (X%)`.

### Batch mode (`--batch`)

For large runs, `--batch` submits every cache-miss job to the [OpenAI Batch API](https://platform.openai.com/docs/guides/batch) as a single job — roughly half the per-token cost, at the price of latency (the run blocks polling until the batch completes):

```bash
uv run job-scraper-9000 remote-filter --run-date 2026-05-16 --batch
```

It is a single blocking command: submit → poll → write the same pass/trash outputs as the serial path. Cache hits never enter the batch (so a re-run is cheap), and outputs/telemetry are identical apart from the 50%-discounted cost estimate. `--poll-interval SECONDS` (default 60) controls the status-poll cadence. The Batch API is OpenAI-only — `--batch` with a non-OpenAI provider fails fast with a clear error; drop the flag to run the serial path against ollama.

Each enriched output record contains all original job fields plus:

```json
{
  "_remote_analysis": {
    "reasoning_trace": "The posting says ...",
    "remote_classification": "fully_remote",
    "estimated_travel_days_per_year": null,
    "location_restrictions": [],
    "requires_relocation": false,
    "requires_local_presence": false,
    "timezone_requirements": [],
    "key_phrases": ["Remote", "distributed team"]
  },
  "_filter_result": "pass",
  "_filter_reason": "passed",
  "_filter_metadata": {
    "schema_version": "3.0.0",
    "prompt_hash": "...",
    "commit": "..."
  }
}
```

______________________________________________________________________

## Classification schema

| Classification        | Meaning                                                 |
| --------------------- | ------------------------------------------------------- |
| `fully_remote`        | No physical presence ever expected                      |
| `hybrid`              | Regular in-office days expected                         |
| `onsite_disguised`    | Listed as remote but requires local/commuting presence  |
| `location_restricted` | Genuinely remote but restricted to specific geographies |
| `unclear`             | Description and context do not provide enough signal    |

As of `SCHEMA_VERSION` 3.0.0 the classification captures **remote-ness only**. Travel frequency is no longer a bucket — it lives entirely in the numeric `estimated_travel_days_per_year`, which policy code thresholds (see Filter logic). The retired `remote_with_*_travel` labels still appear in old reviewed data and historical rows (`models.LEGACY_CLASSIFICATIONS`), but the active model never emits them. See [`specs/remote_filter_simplification.md`](../../../specs/remote_filter_simplification.md).

______________________________________________________________________

## Filter logic

A posting is trashed if any configured policy rule rejects it:

- classification is listed under `policy_thresholds.disallowed_classifications`
- estimated travel days exceed `policy_thresholds.travel.max_estimated_days_per_year`
- location restrictions conflict with `USER_LOCATION`
- hard timezone requirements match rejected timezone keywords
- classification is `unclear` and `on_unclear_classification` is `reject`

The `requires_relocation` and `requires_local_presence` flags are **not** gated
here — this global/consolidation layer is permissive on both (see the `relocation`
config above). They are applied **per user** in `pipeline.scoring.score_run` against
each user's stored `UserPolicies`: `requires_relocation` is a veto unless the user is
willing to relocate, and `requires_local_presence` is **location-aware** — a
non-relocating user keeps such jobs when the posting location matches their acceptable
locations, and drops them (out-of-area / ambiguous / no-policy) otherwise. See
[`specs/relocation_policy.md`](../../../specs/relocation_policy.md) §2.1 and §8.

______________________________________________________________________

## Eval workflow

Gold data lives at:

```text
data/eval/ground_truth.jsonl
```

Run synchronous eval:

```bash
uv run scripts/run_remote_filter_eval.py --workers 4
```

Compare eval runs:

```bash
uv run scripts/compare_evals.py --last 5
```

Run lower-cost OpenAI Batch eval:

```bash
uv run python scripts/submit_eval_batch.py --run-id gpt4o_mini_batch
uv run python scripts/poll_eval_batch.py
```

Current 104-record `gpt-4o-mini` smoke baseline:

```text
accuracy:  0.8654
precision: 0.7073
recall:    0.9355
f1:        0.8056
```

Main tuning target: reduce false positives where onsite/location-restricted jobs are predicted as pass.

See [`scripts/README.md`](../../../scripts/README.md) and [`src/agent_eval/README.md`](../../agent_eval/README.md) for full eval details.
