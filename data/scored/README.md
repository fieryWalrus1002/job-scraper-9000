# Data Schema: Scored Job Postings

**Directory Location:** `data/scored/`

**Description:** This directory contains raw scraped job listings that have been processed through the location pre-filtering pipeline and enriched with AI-generated candidate skills-alignment scores.

______________________________________________________________________

## 1. Top-Level Structure

Every file/record in this directory follows this high-level JSON structure:

| Field                    | Type              | Context            | Description                                              |
| ------------------------ | ----------------- | ------------------ | -------------------------------------------------------- |
| `source` to `dedup_hash` | `Standard Keys`   | Raw Scraper Data   | Core metadata and text extracted from the job board.     |
| `_prefilter_*`           | `Metadata Keys`   | Pipeline Ingestion | Boolean and logging data regarding geographic filtering. |
| `_skills_fit_*`          | `Enrichment Keys` | AI Scoring Agent   | Evaluation metrics, gaps, and scoring rationales.        |

______________________________________________________________________

## 2. Field-Level Definitions

### Core Job Data

- **`source`** `(String)`: The originating platform of the job posting (e.g., `"sel"`, `"linkedin"`).

- **`source_job_id`** `(String)`: Unique identifier assigned by the source platform.

- **`source_url`** `(String)`: Canonical URL to the original job posting.

- **`title`** `(String)`: Explicit job position title.

- **`company`** `(String)`: Name of the hiring organization.

- **`location`** `(String)`: Text representation of the job location.

- **`posted_at`** `(String, YYYY-MM-DD)`: The date the job was published.

- **`description`** `(String)`: Unstructured full-text breakdown of job duties, requirements, and benefits.

- **`scraped_at`** `(String, ISO 8601 Timestamp)`: Exact time the data was pulled.

- **`scrub_counts`** `(Object)`: Tracks PII removal metrics.

- `email` `(Integer)`: Count of redacted email addresses.

- `phone` `(Integer)`: Count of redacted phone numbers.

- **`search_params`** `(Object)`: Query inputs utilized by the scraper agent.

- **`dedup_hash`** `(String)`: SHA-256 hash of core fields used to prevent database duplication.

### Prefilter Metadata (Pipeline Logic)

- **`_prefilter_result`** `(String)`: Status of location verification (e.g., `"local_candidate"`).
- **`_prefilter_reason`** `(String)`: Text snippet explaining the routing decision.
- **`_prefilter_metadata`** `(Object)`: Operational tracing data containing `schema_version`, `config_hash`, `routed_at` timestamp, and specific matched rules (e.g., `["local_area_allowlist"]`).

### Skills Fit Enrichment (AI Agent Outputs)

- **`_skills_fit_score`** `(Integer, 1-5)`: Quantitative score mapping candidate profile to job requirements.
- **`_skills_fit_confidence`** `(String)`: Agent's internal confidence metric (`"high"`, `"medium"`, `"low"`).
- **`_skills_fit_rationale`** `(String)`: High-level overview explaining the alignment score.
- **`_skills_fit_top_matches`** `(Array [String])`: List of explicit overlaps between candidate experience and role needs.
- **`_skills_fit_gaps`** `(Array [String])`: Discrepancies, missing skills, or leveling mismatches.
- **`_skills_fit_hard_concerns`** `(Array [String])`: Red flags or strict prerequisites (e.g., drug screens, specific on-site requirements).
- **`_skills_fit_analysis`** `(Object)`: The raw JSON block containing nested copies of the score, gaps, matches, and parsed `core_job_duties`.
- **`_skills_fit_metadata`** `(Object)`: Model operational tracing (e.g., `model`: `"gpt-5.4-mini"`, `temperature`, prompt file hashes, and execution timestamps).

______________________________________________________________________

## 3. Example Empty Payload Structure

For automated agents generating or parsing this data, ensure payloads mimic this structural shape:

```json
{
  "source": "",
  "source_job_id": "",
  "source_url": "",
  "title": "",
  "company": "",
  "location": "",
  "posted_at": "YYYY-MM-DD",
  "description": "",
  "scraped_at": "YYYY-MM-DDTHH:MM:SS.ffffff+00:00",
  "scrub_counts": { "email": 0, "phone": 0 },
  "search_params": {},
  "dedup_hash": "",
  "_prefilter_result": "",
  "_prefilter_reason": "",
  "_prefilter_metadata": {},
  "_skills_fit_score": 0,
  "_skills_fit_rationale": "",
  "_skills_fit_hard_concerns": [],
  "_skills_fit_top_matches": [],
  "_skills_fit_analysis": {},
  "_skills_fit_gaps": [],
  "_skills_fit_confidence": "",
  "_skills_fit_input_source": "",
  "_skills_fit_metadata": {}
}

See `data/scored/scored_job_schema.json` for the full JSON Schema definition with validation rules and example values.

```
