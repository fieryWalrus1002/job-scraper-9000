# remote-filter

A structured-output LLM agent that reads job descriptions and classifies their remote work policy. Catches the gotchas that keyword filters miss — travel requirements, local presence clauses, timezone lockdowns disguised as "remote" roles.

## Commands

### label

Interactively label jobs from `data/raw/` to build the eval suite. Run this before evaluating agent accuracy.

```bash
uv run agents remote-filter label
```

For each unlabeled posting, you'll see the title, company, and description, then be prompted for:
- **Classification** — which remote category best fits (1-8)
- **Should pass filter** — `y` or `n` based on your preferences
- **Travel days range** — e.g. `0-4`, `12-24`, or blank
- **Notes** — anything worth remembering about this label

Labels are saved to `data/eval/remote_filter_eval.jsonl`. Already-labeled jobs are skipped on subsequent runs, so you can label in batches.

### run

Run the agent against job data and split into pass/trash.

```bash
# Run on all files in data/raw/
uv run agents remote-filter run

# Run on a single file
uv run agents remote-filter run --input data/raw/2026-05-11_linkedin_ai-engineer.jsonl
```

Options:

| Flag | Default | Notes |
| --- | --- | --- |
| `--input PATH` | `data/raw/` | Directory of JSONL files, or a single JSONL file |
| `--max-travel` | `quarterly` | `none`, `quarterly`, or `monthly` |
| `--unclear-routing` | `pass` | What to do with `unclear` classifications: `pass` or `reject` |
| `--location` | `USA` | Your location, used to check geographic restrictions |

Output:
- `data/filtered/remote_filter_pass.jsonl` — postings that passed
- `data/trash/remote_filter_trash.jsonl` — postings that were rejected, with reason

Each output record contains all original job fields plus:
```json
{
  "_remote_analysis": { "remote_classification": "...", "confidence": "high", "reasoning": "..." },
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
- `f` — flip (agent was wrong — adds to eval suite with the correct label)
- `d` — show full description (when the summary isn't enough to judge)
- `s` — skip
- `q` — quit

Start with `--bucket trash` — that's where false negatives hide (real remote jobs the agent wrongly killed). Jobs you flip are written automatically to `data/eval/remote_filter_eval.jsonl` as labeled eval records.

## Classification schema

| Classification | Meaning |
| --- | --- |
| `fully_remote` | No physical presence ever expected |
| `remote_with_quarterly_travel` | Travel ≤ 4×/year |
| `remote_with_monthly_travel` | Travel 5–12×/year |
| `remote_with_frequent_travel` | Travel >12×/year or 25%+ of role |
| `hybrid` | Regular in-office days expected |
| `onsite_disguised` | Listed as remote but requires local presence |
| `location_restricted` | Genuinely remote but geo-restricted |
| `unclear` | Description doesn't say enough to classify |

## Filter logic

Given `--max-travel quarterly` (default), a posting is trashed if:
- `requires_relocation` is true
- `requires_local_presence` is true
- Classification is `hybrid` or `onsite_disguised`
- Classification is `remote_with_frequent_travel`
- Classification is `remote_with_monthly_travel`
- Location restrictions are incompatible with `--location`

`unclear` postings pass by default (`--unclear-routing pass`) — better to review a false positive than miss a real opportunity.

## Eval suite

The eval suite lives in `data/eval/remote_filter_eval.jsonl`. Each record is a human-labeled posting with the expected classification and filter decision. Use it to measure agent accuracy and catch regressions when you iterate the prompt.

Run `label` periodically as new jobs come in to keep the eval set fresh.
