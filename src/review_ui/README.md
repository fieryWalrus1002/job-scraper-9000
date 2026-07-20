# Remote-filter Review UI

A Streamlit app for human-in-the-loop (HITL) verification of remote-filter classifier proposals. You step through production-classified jobs, read the model rationale, and either confirm the 3-way classification or correct it. Confirmed/corrected records land in the local gold layer used by remote-filter evals.

______________________________________________________________________

## Where this fits in the pipeline

```text
job-scraper-9000 remote-filter
    ↓
data/filtered/remote_filter_classified.jsonl
    ↓
scripts/sample_for_review.py
    ↓
data/staging/to_review.jsonl      ← app reads here
    ↓ confirm / correct
data/eval/ground_truth.jsonl      ← app writes here
    ↓
scripts/run_remote_filter_eval.py
```

The old remote-filter teacher batch bootstrap was retired in Phase 32. New gold is proposed by the production classifier (`_remote_analysis`) and human-ratified here.

______________________________________________________________________

## Running

```bash
uv run scripts/sample_for_review.py --n 50
uv run streamlit run src/review_ui/app.py
```

The app reads from:

```text
data/staging/to_review.jsonl
```

If that file does not exist, run remote-filter first, then `uv run scripts/sample_for_review.py`.

______________________________________________________________________

## What the app shows

Each record is displayed in two columns.

**Left — Job posting**

- Title, company, location, source
- Search context when present
- Full job description

**Right — Classifier proposal**

- Reasoning trace
- Suggested legacy verdict (`pass` for `remote`, `trash` for `hybrid`/`onsite`)
- 3-way remote classification
- Timezone requirements and key phrases when present

______________________________________________________________________

## Actions

| Button               | What it does                                                                                          |
| -------------------- | ----------------------------------------------------------------------------------------------------- |
| **Confirm Proposal** | Accepts the classifier proposal as-is. Writes record to gold with `_corrected: false`.                |
| **Save Correction**  | Saves your chosen 3-way classification + verdict. Writes `_corrected: true` and your correction note. |
| **Skip**             | Moves to the next record without writing anything. Use for non-jobs or cases you want to revisit.     |

A progress grid shows how far through the staging file you are.

______________________________________________________________________

## Gold layer output

Both confirm and correct append to:

```text
data/eval/ground_truth.jsonl
```

Each record is the full classified job plus human-review fields:

```json
{
  "_remote_analysis": {
    "remote_classification": "remote",
    "reasoning_trace": "..."
  },
  "_human_verdict": "pass",
  "_human_policy": "remote",
  "_human_classification": "remote",
  "_corrected": false,
  "_review_metadata": {
    "schema_version": "5.0.0",
    "prompt_hash": "...",
    "commit": "..."
  }
}
```

Corrected records also include:

```json
{
  "_corrected": true,
  "_correction_note": "Body is silent on remote work; named-city role is onsite"
}
```

The gold dataset is append-only. Eval loading treats later records with the same `dedup_hash` as overrides, so re-reviewing a job can supersede an earlier label.

______________________________________________________________________

## Remote classification labels

The correction form uses the active 3-way axis only:

| Label    | Meaning                                                                 |
| -------- | ----------------------------------------------------------------------- |
| `remote` | No required office presence; geo/timezone gates are fields, not classes |
| `hybrid` | Regular in-office/local presence is expected                            |
| `onsite` | Physical presence is the default or explicit requirement                |

Legacy labels may still appear in old gold rows for historical audit (`fully_remote`, `onsite_disguised`, `location_restricted`, travel buckets, `unclear`), but new review saves always write the 3-way `_human_classification`.

______________________________________________________________________

## Expected input format

The app expects records in `data/staging/to_review.jsonl` in the shape produced by `scripts/sample_for_review.py`: original job fields plus the production classifier proposal under `_remote_analysis`.

Simplified example:

```json
{
  "title": "...",
  "company": "...",
  "description": "...",
  "_remote_analysis": {
    "reasoning_trace": "...",
    "remote_classification": "remote",
    "estimated_travel_days_per_year": null,
    "location_restrictions": [],
    "requires_relocation": false,
    "requires_local_presence": false,
    "timezone_requirements": [],
    "key_phrases": ["remote"]
  },
  "_filter_metadata": {
    "schema_version": "5.0.0",
    "prompt_hash": "..."
  }
}
```

If a proposal is missing or malformed, the app shows an error for that record and lets you skip it rather than silently writing bad gold.
