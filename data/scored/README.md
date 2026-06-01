# Data Schema: Scored Job Postings

**Directory Location:** `data/scored/`

**Description:** This directory contains raw scraped job listings processed through the location pre-filtering and remote-filter pipelines, then enriched with AI-generated candidate skills-alignment scores. Records are written as JSONL by the skills-fit runner and partitioned by run date (`data/scored/YYYY-MM-DD/skills_fit_scored.jsonl`).

______________________________________________________________________

## 1. Top-Level Structure

Every record follows this high-level shape:

| Field                   | Type     | Source              | Description                                                   |
| ----------------------- | -------- | ------------------- | ------------------------------------------------------------- |
| `dedup_hash`            | `string` | Dedup pipeline      | SHA-256 key; primary identifier for the record.               |
| `source` … `scraped_at` | various  | Raw scraper         | Core job posting fields (title, company, location, etc.).     |
| `remote_classification` | `string` | Remote-filter agent | Typed enum classifying the remote-work policy of the role.    |
| `pipeline_metadata`     | `object` | Pipeline internals  | Prefilter, remote-filter, scrub counts, and search params.    |
| `ai_fit`                | `object` | Skills-fit agent    | Score, confidence, rationale, matches, gaps, and duties.      |
| `metadata`              | `object` | Runner provenance   | Run ID, model, prompt hash, profile version, timestamps, etc. |

______________________________________________________________________

## 2. Field-Level Definitions

### Core Job Data

- **`dedup_hash`** `(String)`: SHA-256 hash of core fields used to deduplicate across batches.
- **`source`** `(String)`: Originating platform (e.g., `"sel"`, `"linkedin"`).
- **`source_job_id`** `(String)`: Unique identifier assigned by the source platform.
- **`source_url`** `(String)`: Canonical URL to the original job posting.
- **`title`** `(String)`: Job position title.
- **`company`** `(String)`: Name of the hiring organisation.
- **`location`** `(String)`: Free-text location from the posting.
- **`posted_at`** `(String, YYYY-MM-DD)`: Date the job was published.
- **`description`** `(String)`: Full raw text of the job description.
- **`scraped_at`** `(String, ISO 8601)`: Timestamp when the posting was ingested.

### Remote Classification

- **`remote_classification`** `(String, enum)`: One of `fully_remote`, `remote_with_quarterly_travel`, `remote_with_monthly_travel`, `remote_with_frequent_travel`, `hybrid`, `onsite_disguised`, `location_restricted`, `unclear`. Produced by the remote-filter agent.

### Pipeline Metadata

**`pipeline_metadata`** `(Object)`: Internal pipeline keys not relevant to downstream consumers. Contains:

- `scrub_counts` — `{email: int, phone: int}` PII-removal metrics.
- `search_params` — Query parameters passed to the scraper.
- `_prefilter_result`, `_prefilter_reason`, `_prefilter_metadata` — Prefilter routing output.
- `_remote_analysis`, `_filter_result`, `_filter_reason`, `_filter_metadata` — Remote-filter analysis output.

### AI Skills-Fit Analysis (`ai_fit`)

**`ai_fit`** `(Object | null)`: `null` when scoring failed or was skipped (`failure_reason` in `metadata` explains why).

- **`fit_score`** `(Integer, 1–5)`: 1 = reject, 2 = weak, 3 = possible, 4 = good, 5 = strong.
- **`confidence`** `(String)`: `"low"`, `"medium"`, or `"high"` — how reliably the JD conveys requirements.
- **`score_rationale`** `(String)`: Evidence-based explanation of the score.
- **`top_matches`** `(Array[String])`: 2–5 specific overlaps with the candidate profile.
- **`gaps`** `(Array[String])`: 2–5 missing requirements or misalignments.
- **`hard_concerns`** `(Array[String])`: Hard blockers — clearance, location, credential, work authorisation.
- **`core_job_duties`** `(Array[String])`: 4–5 most important duties, quoted verbatim from the JD where possible.

### Run Provenance (`metadata`)

**`metadata`** `(Object)`: Operational provenance for the scoring run.

- **`run_id`** `(String)`: Unique ID for the pipeline run.
- **`scored_at`** `(String, ISO 8601)`: Timestamp when the record was scored.
- **`model`**, **`provider`** `(String)`: LLM used (e.g., `"gpt-4o-mini"`, `"openai"`).
- **`profile_version`** `(String)`: Version of the candidate profile used for scoring.
- **`failure_reason`** `(String | null)`: `"missing_description"` or `"agent_failed"` when `ai_fit` is null.
- **`prompt_hash`**, **`profile_hash`** `(String)`: SHA-256 hashes of the prompt and profile files at run time.
- **`commit`**, **`dirty`**: Git commit SHA and working-tree state at run time.
- **`input_source`** `(String)`: `"remote_filter_pass"` or `"local_candidate"`.

______________________________________________________________________

## 3. Example Record Shape

```json
{
  "dedup_hash": "abc123",
  "source": "linkedin",
  "source_job_id": "12345",
  "source_url": "https://linkedin.com/jobs/view/12345",
  "title": "Senior Data Engineer",
  "company": "Acme Corp",
  "location": "Remote",
  "posted_at": "2026-05-28",
  "description": "...",
  "scraped_at": "2026-05-28T10:00:00+00:00",
  "remote_classification": "fully_remote",
  "pipeline_metadata": {
    "scrub_counts": { "email": 0, "phone": 1 },
    "search_params": {},
    "_prefilter_result": "remote_filter_pass",
    "_prefilter_reason": "remote keyword match"
  },
  "ai_fit": {
    "fit_score": 4,
    "confidence": "high",
    "score_rationale": "Strong Azure and Python overlap; no clearance requirement.",
    "top_matches": ["Azure Data Factory", "Python", "ETL pipelines"],
    "gaps": ["Databricks certification preferred"],
    "hard_concerns": [],
    "core_job_duties": ["Design and maintain ADF pipelines", "Collaborate with data scientists"]
  },
  "metadata": {
    "run_id": "skillsfit-20260528-abc",
    "scored_at": "2026-05-28T11:00:00+00:00",
    "model": "gpt-4o-mini",
    "provider": "openai",
    "profile_version": "1.3.0",
    "failure_reason": null,
    "prompt_hash": "deadbeef",
    "profile_hash": "cafebabe",
    "commit": "ff79e79",
    "dirty": false,
    "input_source": "remote_filter_pass",
    "input_path": "data/remote_filter/2026-05-28/remote_filter_pass.jsonl",
    "skills_fit_schema_version": "1.0.0"
  }
}
```

See `schemas/scored_job_schema.json` for the full JSON Schema definition with validation rules.
