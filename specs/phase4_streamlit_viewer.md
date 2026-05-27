# Phase 4: Streamlit Job Review UI

_Status: Design — not yet implemented_

______________________________________________________________________

## Purpose

Provide a daily-usable browser UI for reviewing scored job postings produced by the skills-fit pipeline. The viewer must support browsing across multiple run-dates, filtering by score and date range, and reading full job details including rationale and concerns.

This is a read-only tool for Phase 4 MVP. Application status tracking, notes, and dispatch/email are out of scope here.

______________________________________________________________________

## Relationship to prior work

- Reads output of the skills-fit production runner: `data/scored/{DATE}/skills_fit_scored.jsonl`
- Does not re-score, modify, or write to scored files
- The CLI viewer (`scripts/view_skills_fit_results.py`, spec `skills_fit_results_viewer.md`) covers single-run terminal inspection; this spec covers multi-run browser UI

______________________________________________________________________

## Open question: data backend

How should the viewer load scored records? Two options:

### Option A — JSONL on demand

Load all `data/scored/*/skills_fit_scored.jsonl` files at startup (or on user interaction), concatenate into a DataFrame in memory, apply filters, and render.

**Pros:**

- No new infrastructure — no DB, no import step, no sync problem
- Always reflects the current state of files on disk
- Simple to implement and reason about

**Cons:**

- Full re-scan of all dated files on every page interaction (Streamlit re-runs the whole script on each widget change)
- Slow once there are many run-dates or large files (341 records × N days)
- No place to attach per-job metadata (status, notes) without adding a sidecar file

**Mitigation if we go this route:**

- `@st.cache_data` with `ttl` or manual invalidation to avoid re-reading files on every widget change
- Cache keyed on file mtimes so a new run-date is picked up automatically

### Option B — SQLite backing store

An import script reads all `data/scored/*/skills_fit_scored.jsonl` files and upserts into a local SQLite DB (`data/jobs.db`). The viewer queries the DB.

**Pros:**

- Fast cross-date queries (indexed by run_date, fit_score, dedup_hash)
- Natural place to add per-job metadata tables later (status, notes)
- Import script is separate from the viewer — no startup latency

**Cons:**

- Import step must be run after each new scored file lands; viewer can show stale data if import is forgotten
- More moving parts: import script + DB file + viewer

**Mitigation if we go this route:**

- Import script is idempotent (upsert by dedup_hash + run_date); safe to re-run
- Viewer detects when any scored file is newer than the DB and shows a banner prompting re-import
- DB file lives in `data/` and is gitignored

### Recommendation

Start with **Option A** (JSONL on demand with `st.cache_data`). It keeps Phase 4 MVP self-contained and avoids an import step. If performance becomes painful at scale (many run-dates), migrate to Option B — the viewer logic is the same; only the data-loading layer changes.

This spec is written for Option A. Option B differences are noted where they arise.

______________________________________________________________________

## Scope

### In scope

- Streamlit app at `src/ui/viewer.py`
- Launch via `uv run streamlit run src/ui/viewer.py`
- Multi-date browsing with a date-window selector
- Score cutoff filter (minimum fit_score)
- Per-job detail expansion (rationale, top matches, gaps, hard concerns, job description, URL)
- Sorting by fit_score descending (primary) and run_date descending (secondary)
- Hard-concern flagging in the list view

### Out of scope

- Application status tracking (applied, interview, offer, rejected)
- Per-job notes or Obsidian sync
- Email/digest dispatch
- Re-scoring or editing records
- Any writes to scored JSONL files

______________________________________________________________________

## Data model

Each record in `data/scored/{DATE}/skills_fit_scored.jsonl` has (fields consumed by the viewer):

| Field                       | Type             | Notes                                     |
| --------------------------- | ---------------- | ----------------------------------------- |
| `_skills_fit_score`         | int 1–5          | Primary ranking key                       |
| `_skills_fit_confidence`    | str              | low / medium / high                       |
| `_skills_fit_rationale`     | str              | Shown in detail view                      |
| `_skills_fit_top_matches`   | list[str]        | Shown in detail view                      |
| `_skills_fit_gaps`          | list[str]        | Shown in detail view                      |
| `_skills_fit_hard_concerns` | list[str]        | Shown in list + detail                    |
| `title`                     | str              | Job title                                 |
| `company`                   | str              | Company name                              |
| `location`                  | str              | Location string                           |
| `job_url`                   | str              | Link to original posting                  |
| `description`               | str              | Full JD text (collapsed by default)       |
| `salary_range`              | str              | May be null                               |
| `run_date`                  | str (YYYY-MM-DD) | Injected at load time from directory name |

The viewer injects `run_date` at load time from the directory name of each file (not from the record itself, since the field may not be present in all records).

______________________________________________________________________

## UI layout

### Sidebar — filters

```
[ Date range ]
  From: [date picker]  To: [date picker]
  Preset buttons: Today | Last 7 days | All

[ Score filter ]
  Minimum fit score: [slider 1–5, default 3]

[ Concern filter ]
  [ ] Hide jobs with hard concerns

[ Sort ]
  (fixed: score desc, then date desc — no user control needed for MVP)
```

Date range defaults to **today's run-date** (the most recent `data/scored/` partition) on first load.

### Main panel — job list

A table or card list showing all jobs that pass the active filters, sorted by fit_score desc then run_date desc.

Columns:

| Column   | Source                      | Notes                                   |
| -------- | --------------------------- | --------------------------------------- |
| Score    | `_skills_fit_score`         | Shown as 1–5 with color band            |
| Conf.    | `_skills_fit_confidence`    | low / med / high abbreviation           |
| Title    | `title`                     |                                         |
| Company  | `company`                   |                                         |
| Location | `location`                  |                                         |
| Date     | `run_date`                  | YYYY-MM-DD                              |
| Concerns | `_skills_fit_hard_concerns` | `⚠` badge if non-empty, blank otherwise |

Score color banding:

- 5 — green
- 4 — light green
- 3 — yellow
- 2 — orange
- 1 — red

Row count shown above the list: `N jobs shown (M total across selected dates)`.

### Detail view

Clicking a row (or an "expand" button) opens a detail panel below the list (or in a sidebar expander). Contents:

**Header:**

- Title, Company, Location, run_date
- Fit score badge + confidence
- Link to original posting (job_url)
- Salary range (if present)

**Fit analysis:**

- `score_rationale` (full text)
- Top matches (bulleted list)
- Gaps (bulleted list)
- Hard concerns (bulleted list, highlighted if non-empty)

**Job description:**

- Collapsed by default (`st.expander("Full job description")`)
- Full `description` text inside

______________________________________________________________________

## File layout

```
src/ui/
    viewer.py        — Streamlit app entry point
    loader.py        — data loading and caching logic (JSONL scan, DataFrame construction)
```

Keeping loader logic in a separate module makes it easy to swap Option A for Option B later without touching viewer.py.

______________________________________________________________________

## Data loading (Option A)

`loader.py` exposes one function:

```
load_scored_jobs(data_dir: Path, min_date: date, max_date: date) -> pd.DataFrame
```

- Scans `data_dir/scored/*/skills_fit_scored.jsonl` for partitions within the date range
- Reads each JSONL file line by line, skipping malformed lines with a warning
- Injects `run_date` from the directory name
- Concatenates into a single DataFrame
- Decorated with `@st.cache_data` keyed on `(min_date, max_date, file_mtimes_hash)` so re-reads only happen when files change

If Option B (SQLite) is adopted later: `loader.py` is replaced with a SQL query; `viewer.py` is unchanged.

______________________________________________________________________

## Launch

```bash
uv run streamlit run src/ui/viewer.py
```

No CLI arguments; all configuration is via sidebar widgets. The app discovers available run-dates automatically from the `data/scored/` directory.

______________________________________________________________________

## Failure behavior

- If `data/scored/` does not exist or contains no dated partitions: show an informative placeholder ("No scored runs found. Run the pipeline first.")
- If a JSONL file exists but is empty: skip silently
- Malformed JSONL lines: skip with a `st.warning` summary (e.g., "3 malformed lines skipped across 2 files")
- If a record is missing `_skills_fit_score`: include it with score rendered as `—` and sort it last

______________________________________________________________________

## Non-goals / future follow-ons

- Application status (applied / interview / offer / rejected) — Phase 5
- Per-job markdown notes and Obsidian sync — Phase 5
- Email digest of daily shortlist — separate dispatch spec
- Pairwise reranking of top-bucket jobs — separate spec
- Full-text search across job descriptions — post-MVP
- Export to CSV or clipboard — post-MVP
- SQLite migration — triggered by performance, not by this spec
