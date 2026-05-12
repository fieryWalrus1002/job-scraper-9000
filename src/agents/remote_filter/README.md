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

## Commands

### run

Run the agent against job data and split into pass/trash.

```bash
# Run on all files in data/raw/ with default config
uv run agents remote-filter run

# Specify your location (used for geographic restriction checks)
uv run agents remote-filter run --location "Pullman, WA"

# Run on a single file
uv run agents remote-filter run --input data/raw/2026-05-11_linkedin_ai-engineer.jsonl

# Use a different config (e.g. a more permissive one for testing)
uv run agents remote-filter run --config config/agent/permissive.yml
```

Options:

| Flag | Default | Notes |
| --- | --- | --- |
| `--input PATH` | `data/raw/` | Directory of JSONL files, or a single JSONL file |
| `--config FILE` | `config/agent/remote_agent.yml` | Policy config YAML |
| `--location` | `USA` | Your location, used to check geographic restrictions |

Output:
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

### review

Interactively review agent decisions. Shows each job with the agent's full reasoning and lets you confirm or override.

```bash
uv run agents remote-filter review              # review trash (default — catch false negatives)
uv run agents remote-filter review --bucket pass   # review pass (catch false positives)
uv run agents remote-filter review --bucket all    # review everything
```

For each job you'll see: title, company, URL, classification, confidence, the agent's reasoning, travel details, and any location/relocation flags.

Keys:

- `k` — keep (agent was correct, no action)
- `f` — flip (agent was wrong — prompts for correct classification, key phrases, and notes, then adds to eval suite)
- `d` — show full description with key phrases highlighted in yellow
- `s` — skip
- `q` — quit

Start with `--bucket trash` — that's where false negatives hide (real remote jobs the agent wrongly killed). Jobs you flip are written to `data/eval/remote_filter_eval.jsonl` as labeled eval records.

### label

Interactively label raw jobs from `data/raw/` to build the eval suite from scratch. Use this if you want to label jobs before running the agent.

```bash
uv run agents remote-filter label
```

For each unlabeled posting you'll be prompted for:
- **Classification** — which remote category best fits (1-8)
- **Should pass filter** — `y` or `n`
- **Travel days range** — e.g. `0-4`, `12-24`, or blank
- **Key phrases** — comma-separated verbatim excerpts from the posting that support the label
- **Notes** — anything worth remembering

Labels are saved to `data/eval/remote_filter_eval.jsonl`. Already-labeled jobs are skipped on subsequent runs, so you can label in batches.

### export

Export the eval suite as an OpenAI fine-tuning JSONL.

```bash
uv run agents remote-filter export
```

Reads `data/eval/remote_filter_eval.jsonl` and writes `data/eval/remote_filter_finetune.jsonl` — one training example per record in OpenAI's `{"messages": [...]}` format, ready to upload for fine-tuning.

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
