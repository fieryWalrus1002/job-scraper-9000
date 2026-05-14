# Review UI

A Streamlit app for human-in-the-loop (HITL) verification of teacher model reasoning. You step through each job the teacher annotated, read its reasoning trace, and either confirm the verdict or correct it. Confirmed and corrected records land in the gold layer as ground truth for student model training.

---

## Where this fits in the pipeline

```text
scripts/prepare_batch.py    → data/raw/gpt_teacher_batch.jsonl
[upload to OpenAI Batch API, download results]
scripts/merge_batch_results.py → data/staging/to_review.jsonl   ← app reads here
         ↓ confirm / correct
data/eval/ground_truth.jsonl                                     ← app writes here
```

See [scripts/README.md](../../scripts/README.md) for the full batch preparation workflow.

---

## Running

```bash
streamlit run src/review_ui/app.py
```

The app reads from `data/staging/to_review.jsonl`. If that file doesn't exist, it will prompt you to run `merge_batch_results.py` first.

---

## What the app shows

Each record is displayed in two columns:

**Left — Job posting**
- Title, company, location, source
- Full job description

**Right — Teacher reasoning**
- Reasoning trace (the teacher's step-by-step logic)
- Verdict (`pass` or `trash`)
- Remote policy classification
- Key phrases the teacher cited

---

## Actions

| Button | What it does |
| --- | --- |
| **Confirm Teacher** | Accepts the teacher's verdict and policy as-is. Writes record to gold layer with `_corrected: false`. |
| **Save Correction** | Saves your chosen policy + verdict instead. Writes with `_corrected: true` and your correction note. |
| **Skip** | Moves to the next record without writing anything. Use for ambiguous cases you want to revisit. |

A progress bar shows how far through the batch you are.

---

## Gold layer output

Both confirm and correct write to `data/eval/ground_truth.jsonl`. Each record is the full merged job (original fields + teacher response) plus these added fields:

```json
{
  "_human_verdict": "pass",
  "_human_policy": "fully_remote",
  "_corrected": false
}
```

Corrected records also include:

```json
{
  "_corrected": true,
  "_correction_note": "Says remote but requires Seattle presence for onboarding"
}
```

The `_corrected` flag lets you filter the dataset later — e.g. train only on corrected records, or measure teacher accuracy by counting corrections.

---

## Remote policy labels

The correction form uses this label set (aligned with the student agent's classification schema):

| Label | Meaning |
| --- | --- |
| `fully_remote` | No office requirement, no material travel |
| `hybrid` | Regular in-office days expected |
| `onsite` | Office-required role listed without remote option |
| `onsite_disguised` | Listed as remote but requires local presence |
| `unclear` | Description doesn't provide enough signal |

---

## Expected input format

The app expects records in `data/staging/to_review.jsonl` in the shape produced by `merge_batch_results.py` — each line is a merged job with the teacher's OpenAI Batch API response embedded under the `response` key:

```json
{
  "title": "...",
  "company": "...",
  "description": "...",
  "response": {
    "status_code": 200,
    "body": {
      "choices": [{
        "message": {
          "content": "{\"reasoning_trace\": \"...\", \"remote_policy\": \"fully_remote\", \"pass_or_trash\": \"pass\", \"key_phrases\": [\"...\"]}"
        }
      }]
    }
  },
  "_batch_custom_id": "job-42"
}
```

If the teacher response JSON is malformed, the app shows an error for that record and lets you skip it rather than crashing.
