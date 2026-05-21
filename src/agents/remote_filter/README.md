# remote-filter

A structured-output LLM agent that reads job descriptions and classifies their remote-work policy. It catches issues that keyword filters miss: travel requirements, local presence clauses, relocation language, hard timezone constraints, and location restrictions disguised as remote roles.

---

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
  provider: openai        # openai | ollama
  model: gpt-4o-mini
  temperature: 0.1
  # base_url: http://localhost:11434/v1   # uncomment for ollama

policy_thresholds:
  disallowed_classifications:
    - "onsite_disguised"
    - "hybrid"
    - "onsite"

  travel:
    max_estimated_days_per_year: 15
    prohibited_categories:
      - "remote_with_frequent_travel"

  relocation:
    allow_required_relocation: false
    allow_local_presence_required: false

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

---

## Running the agent

The CLI reads the routed candidate JSONL from `data/prefiltered/remote_filter_input.jsonl` by default, applies the remote filter, and writes pass/trash outputs:

```bash
uv run job-scraper remote-filter
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

Across-batch analyses are cached at `data/cache/remote_filter_analyses.jsonl`, keyed by `(dedup_hash, prompt_hash, model)`. Cache hits skip the LLM call entirely; misses append the new analysis. The key includes `prompt_hash` and `model`, so prompt edits or model swaps invalidate automatically. Pass `--no-cache` to bypass, or `--cache-path` to point elsewhere. The run summary logs `cache N/M hits (X%)`.

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
    "schema_version": "2.0.0",
    "prompt_hash": "...",
    "commit": "..."
  }
}
```

---

## Classification schema

| Classification | Meaning |
| --- | --- |
| `fully_remote` | No physical presence ever expected |
| `remote_with_quarterly_travel` | Remote with travel roughly quarterly or less |
| `remote_with_monthly_travel` | Remote with travel roughly monthly |
| `remote_with_frequent_travel` | Remote with frequent/material travel, e.g. >12 days/year or 25%+ |
| `hybrid` | Regular in-office days expected |
| `onsite_disguised` | Listed as remote but requires local/commuting presence |
| `location_restricted` | Genuinely remote but restricted to specific geographies |
| `unclear` | Description and context do not provide enough signal |

Legacy labels may appear in old reviewed data, but the active model schema is the list above.

---

## Filter logic

A posting is trashed if any configured policy rule rejects it:

- `requires_relocation` is true and relocation is not allowed
- `requires_local_presence` is true and local presence is not allowed
- classification is listed under `policy_thresholds.disallowed_classifications`
- classification is listed under `policy_thresholds.travel.prohibited_categories`
- estimated travel days exceed `policy_thresholds.travel.max_estimated_days_per_year`
- location restrictions conflict with `USER_LOCATION`
- hard timezone requirements match rejected timezone keywords
- classification is `unclear` and `on_unclear_classification` is `reject`

---

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
