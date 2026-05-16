# Review UI

A Streamlit app for human-in-the-loop (HITL) verification of teacher model reasoning. You step through each teacher-annotated job, read the rationale, and either confirm the verdict or correct it. Confirmed/corrected records land in the gold layer used by remote-filter evals and future local-model distillation.

---

## Where this fits in the pipeline

```text
scripts/prepare_batch.py
    ↓
OpenAI Batch API teacher run
    ↓
scripts/merge_batch_results.py
    ↓
data/staging/to_review.jsonl      ← app reads here
    ↓ confirm / correct
data/eval/ground_truth.jsonl      ← app writes here
    ↓
scripts/run_remote_filter_eval.py / scripts/submit_eval_batch.py
```

See [`scripts/README.md`](../../scripts/README.md) for the full batch preparation and eval workflow.

---

## Running

```bash
streamlit run src/review_ui/app.py
```

The app reads from:

```text
data/staging/to_review.jsonl
```

If that file does not exist, run the teacher batch preparation/merge flow first.

---

## What the app shows

Each record is displayed in two columns.

**Left — Job posting**

- Title, company, location, source
- Full job description

**Right — Teacher reasoning**

- Reasoning trace
- Teacher verdict (`pass` or `trash`)
- Remote policy classification
- Key phrases cited by the teacher

---

## Actions

| Button | What it does |
| --- | --- |
| **Confirm Teacher** | Accepts the teacher verdict and policy as-is. Writes record to gold with `_corrected: false`. |
| **Save Correction** | Saves your chosen policy + verdict instead. Writes with `_corrected: true` and your correction note. |
| **Skip** | Moves to the next record without writing anything. Use for ambiguous cases you want to revisit. |

A progress bar shows how far through the staging file you are.

---

## Gold layer output

Both confirm and correct write to:

```text
data/eval/ground_truth.jsonl
```

Each record is the full merged job plus human-review fields:

```json
{
  "_human_verdict": "pass",
  "_human_policy": "fully_remote",
  "_corrected": false,
  "_review_metadata": {
    "schema_version": "2.0.0",
    "prompt_hash": "...",
    "commit": "..."
  }
}
```

Corrected records also include:

```json
{
  "_corrected": true,
  "_correction_note": "Says remote but requires Seattle presence for onboarding"
}
```

The gold dataset is append-only. Eval loading treats later records with the same `dedup_hash` as overrides, so re-reviewing a job can supersede an earlier label.

---

## Remote policy labels

The correction form uses the active schema plus legacy labels that may appear in older teacher runs.

Active labels:

| Label | Meaning |
| --- | --- |
| `fully_remote` | No office requirement and no material travel |
| `remote_with_quarterly_travel` | Remote with travel roughly quarterly or less |
| `remote_with_monthly_travel` | Remote with travel roughly monthly |
| `remote_with_frequent_travel` | Remote with frequent/material travel |
| `hybrid` | Regular in-office days expected |
| `onsite_disguised` | Listed as remote but requires local/commuting presence |
| `location_restricted` | Genuinely remote but restricted to specific geographies |
| `unclear` | Description and context do not provide enough signal |

Legacy labels still available for old records:

- `remote_with_occasional_travel`
- `onsite`

---

## Expected input format

The app expects records in `data/staging/to_review.jsonl` in the shape produced by `scripts/merge_batch_results.py`: original job fields plus the teacher's OpenAI Batch API response under `response`.

Simplified example:

```json
{
  "title": "...",
  "company": "...",
  "description": "...",
  "response": {
    "status_code": 200,
    "body": {
      "choices": [
        {
          "message": {
            "content": "{\"reasoning_trace\": \"...\", \"remote_classification\": \"fully_remote\", \"estimated_travel_days_per_year\": null, \"location_restrictions\": [], \"requires_relocation\": false, \"requires_local_presence\": false, \"timezone_requirements\": [], \"key_phrases\": [\"remote\"]}"
          }
        }
      ]
    }
  },
  "_batch_custom_id": "job-42"
}
```

If the teacher response JSON is malformed, the app shows an error for that record and lets you skip it rather than crashing.
