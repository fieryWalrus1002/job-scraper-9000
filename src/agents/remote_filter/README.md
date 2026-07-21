# remote-filter

A structured-output LLM agent that reads job descriptions and classifies their remote-work policy. It catches issues that keyword filters miss: travel requirements, local presence clauses, relocation language, hard timezone constraints, and location restrictions disguised as remote roles.

______________________________________________________________________

## Configuration

LLM runtime settings live in [`config/agent/remote_agent.yml`](../../../config/agent/remote_agent.yml). The active system prompt lives separately at:

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
```

Accept/reject policy is not global remote-filter config anymore. The classifier writes profile-independent extraction output; per-user gating happens later in `pipeline.scoring` from stored user policies.

______________________________________________________________________

## Running the agent

The CLI reads the routed candidate JSONL from `data/prefiltered/remote_filter_input.jsonl` by default, runs the remote classifier, and writes one classified output:

```bash
uv run job-scraper-9000 remote-filter
```

The legacy script entry point still works:

```bash
uv run scripts/run_remote_filter.py
```

Output:

- `data/filtered/remote_filter_classified.jsonl`

Override `--input data/raw` if you want to run the filter directly on raw scraped jobs.

Within-batch duplicates (by `dedup_hash`, falling back to `source_job_id`) are collapsed before the LLM step — when the same posting shows up in multiple scrapers in one run, it's analyzed once.

Across-batch analyses are cached at `data/cache/remote_filter_analyses.jsonl`, keyed by `(dedup_hash, prompt_hash, provider, model, context_fp)` — where `dedup_hash` falls back to `source_job_id` when absent, and `context_fp` is a fingerprint of the search-context fields the prompt actually reads (`keywords`, `workplace`, `job_type`, `user_timezone`). Any of: a prompt edit, a model or provider swap, or a change to a context field that affects the prompt → key changes → cache misses and recomputes. No manual invalidation needed. Pass `--no-cache` to bypass, or `--cache-path` to point elsewhere. The run summary logs `cache N/M hits (X%)`.

### Batch mode (`--batch`)

For large runs, `--batch` submits every cache-miss job to the [OpenAI Batch API](https://platform.openai.com/docs/guides/batch) as a single job — roughly half the per-token cost, at the price of latency (the run blocks polling until the batch completes):

```bash
uv run job-scraper-9000 remote-filter --run-date 2026-05-16 --batch
```

It is a single blocking command: submit → poll → write the same classified output as the serial path. Cache hits never enter the batch (so a re-run is cheap), and outputs/telemetry are identical apart from the 50%-discounted cost estimate. `--poll-interval SECONDS` (default 60) controls the status-poll cadence. The Batch API is OpenAI-only — `--batch` with a non-OpenAI provider fails fast with a clear error; drop the flag to run the serial path against ollama.

Each enriched output record contains all original job fields plus:

```json
{
  "_remote_analysis": {
    "reasoning_trace": "The posting says ...",
    "remote_classification": "remote",
    "estimated_travel_days_per_year": null,
    "location_restrictions": [],
    "requires_relocation": false,
    "requires_local_presence": false,
    "timezone_requirements": [],
    "key_phrases": ["Remote", "distributed team"]
  },
  "_filter_result": "pass",
  "_filter_reason": "classified",
  "_filter_metadata": {
    "schema_version": "5.0.0",
    "prompt_hash": "...",
    "commit": "..."
  }
}
```

______________________________________________________________________

## Classification schema

| Classification | Meaning                                                                 |
| -------------- | ----------------------------------------------------------------------- |
| `remote`       | No required office presence; geo/timezone gates are fields, not classes |
| `hybrid`       | Regular in-office/local presence is expected                            |
| `onsite`       | Physical presence is the default or explicit requirement                |

As of `SCHEMA_VERSION` 5.0.0 the classification captures **remote-ness only** on the 3-way axis. Travel frequency lives entirely in the numeric `estimated_travel_days_per_year`, which user-specific policy code thresholds downstream. The retired `unclear`, `fully_remote`, `onsite_disguised`, `location_restricted`, and `remote_with_*_travel` labels still appear in historical reviewed data and DB rows (`models.LEGACY_CLASSIFICATIONS`), but the active model never emits them. See [`specs/remote_filter_taxonomy.md`](../../../specs/remote_filter_taxonomy.md) and [`specs/remote_filter_classifier_tuning.md`](../../../specs/remote_filter_classifier_tuning.md).

______________________________________________________________________

## Downstream gating

The classifier is a pure extractor: it writes every successfully analyzed posting
into the classified stream. Accept/reject decisions happen **per user** in
`pipeline.scoring.score_run` against each user's stored `UserPolicies`, including
`acceptable_classifications`, location restrictions, relocation, and local-presence
policy. See [`specs/relocation_policy.md`](../../../specs/relocation_policy.md) §2.1
and §8.

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

For model bake-offs, run each candidate with `--model`/`--provider`, then render the quality × estimated-cost table:

```bash
uv run scripts/compare_evals.py --bakeoff --last 7
```

Current evals report classifier-native 3-way categorical metrics (`remote`, `hybrid`, `onsite`) plus travel-days diagnostics and estimated list-price cost. Phase 32 uses micro accuracy + `remote` recall as the champion metric pair; the bake-off adds `$ / correct` as the cost tie-breaker. See [`specs/remote_filter_model_bakeoff.md`](../../../specs/remote_filter_model_bakeoff.md), `scripts/run_remote_filter_eval.py`, and `scripts/compare_evals.py`.

See [`scripts/README.md`](../../../scripts/README.md) and [`src/agent_eval/README.md`](../../agent_eval/README.md) for full eval details.
