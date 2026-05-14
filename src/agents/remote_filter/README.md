# remote-filter

A structured-output LLM agent that reads job descriptions and classifies their remote work policy. Catches the gotchas that keyword filters miss — travel requirements, local presence clauses, timezone lockdowns disguised as "remote" roles.

## Configuration

Filter policy lives in `config/agent/remote_agent.yml`. Edit it to change what gets trashed without touching code.

```yaml
extraction:
  provider: "openai"        # or "ollama"
  model: "gpt-4o-mini"
  temperature: 0.1
  system_prompt: |          # full LLM prompt — edit to tune extraction behavior

policy_thresholds:
  disallowed_classifications:
    - "onsite_disguised"
    - "hybrid"
    - "location_restricted"  # remove if you want to review these manually

  travel:
    prohibited_categories:
      - "remote_with_frequent_travel"
      - "remote_with_monthly_travel"   # remove to allow monthly travel
    max_estimated_days_per_year: 15

  relocation:
    allow_required_relocation: false
    allow_local_presence_required: false

  uncertainty:
    on_unclear_classification: "reject"  # or "pass"
```

To allow more travel, remove categories from `prohibited_categories`. To let through uncertain postings for manual review, set `on_unclear_classification: "pass"`.

## Running the agent

The unified CLI was removed in favour of modularity. Use the script directly:

```bash
python scripts/run_remote_filter.py
```

Reads all JSONL files from `data/raw/`, applies the filter policy, and writes:

- `data/filtered/remote_filter_pass.jsonl` — postings that passed
- `data/trash/remote_filter_trash.jsonl` — postings that were rejected, with reason

Each output record contains all original job fields plus:

```json
{
  "_remote_analysis": {
    "remote_classification": "fully_remote",
    "confidence": "high",
    "reasoning": "Explicitly states fully distributed team...",
    "key_phrases": ["fully distributed team", "no office required"]
  },
  "_filter_result": "pass",
  "_filter_reason": "passed"
}
```

See [scripts/README.md](../../scripts/README.md) for the full pipeline (teacher batch, HITL review).

## Classification schema

| Classification | Meaning |
| --- | --- |
| `fully_remote` | No physical presence ever expected |
| `remote_with_quarterly_travel` | Travel ≤ 4×/year |
| `remote_with_monthly_travel` | Travel 5–12×/year |
| `remote_with_frequent_travel` | Travel >12×/year or 25%+ of role |
| `hybrid` | Regular in-office days expected |
| `onsite_disguised` | Listed as remote but requires local presence |
| `location_restricted` | Genuinely remote but geo-restricted (state/region list) |
| `unclear` | Description doesn't say enough to classify |

## Filter logic

A posting is trashed if any of the following are true (driven by `policy_thresholds` in config):

- `requires_relocation` is true
- `requires_local_presence` is true
- Classification is in `disallowed_classifications` (default: `hybrid`, `onsite_disguised`, `location_restricted`)
- Classification is in `travel.prohibited_categories` (default: `remote_with_frequent_travel`, `remote_with_monthly_travel`)
- Estimated travel days exceed `travel.max_estimated_days_per_year`
- Location restrictions are incompatible with `--location`

## Eval suite

The eval suite lives in `data/eval/remote_filter_eval.jsonl`. Each record is a human-labeled posting with the expected classification, filter decision, and key phrases. Use it to measure agent accuracy and catch regressions when you iterate the prompt or config.

Build it up over time via `label` (raw jobs) and `review --bucket trash` (catch agent mistakes). Run `export` to turn it into a fine-tuning dataset.
