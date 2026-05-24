# Skills Fit Results Viewer (#62)

## Purpose

Add the smallest useful read-only viewer for skills-fit scored results.

This spec covers GitHub issue #62 as a tight follow-on to the production runner:

- read scored output from `data/scored/`
- print a ranked shortlist to the terminal
- make hard blockers visible at a glance
- optionally show rationale for the displayed rows

The goal is not a UI. The goal is to quickly inspect the top jobs from a scored run.

---

## Recommended implementation shape

Implement #62 as a CLI script:

- `scripts/view_skills_fit_results.py`

Why:

- small and fast to build
- matches the current script-driven workflow
- enough for this issue
- keeps the feature read-only and low-complexity

No new Streamlit app is needed for this issue.

---

## Relationship to #61

This viewer reads the output of the production runner spec in `specs/skills_fit_production_runner.md`.

Canonical scored input:

- `data/scored/<DATE>/skills_fit_scored.jsonl`

The viewer never computes scores. It only reads and presents scored JSONL.

---

## Scope

### In scope

- Add `scripts/view_skills_fit_results.py`
- Read scored JSONL output
- Print a concise ranked table to the terminal
- Optionally print rationale and hard concerns for displayed rows
- Work with canonical dated partitions
- Support explicit input-path override

### Out of scope

- New Streamlit app
- Filtering beyond limiting the number of rows shown
- Editing or annotating jobs from the viewer
- Re-scoring jobs
- Dispatch/email sending
- Persisting user actions like starred/applied/skipped
- Full-text search
- Arbitrary sorting options
- Browser-open integration

---

## Input resolution

### Canonical mode

When `--run-date YYYY-MM-DD` is provided and no explicit `--input` is given:

- input: `data/scored/<DATE>/skills_fit_scored.jsonl`

### Explicit override

If `--input PATH` is provided, it wins over default resolution.

### Missing required input selector

If neither `--run-date` nor `--input` is provided, the viewer should fail fast with a clear error.

---

## CLI contract

Keep the first version minimal.

Arguments:

- `--run-date YYYY-MM-DD`
- `--input PATH`
- `--limit N`
- `--show-rationale`

Validation rules:

- `--limit` must be `>= 1`
- either `--run-date` or `--input` must be provided

`--limit` applies after malformed lines are skipped and before rendering finishes; practically, it limits the number of displayed valid rows.

---

## Display requirements

### Default table view

Print one row per displayed job with columns:

- rank
- fit score
- blocker flag
- title
- company
- location

Blocker flag behavior:

- blank if `_skills_fit_hard_concerns` is empty
- `BLOCKERS` if `_skills_fit_hard_concerns` is non-empty

Missing strings should render as `-`.

The viewer should preserve file order. The scored file is already ranked by the production runner.

### Expanded detail view

When `--show-rationale` is set, also print for each displayed job:

- score rationale
- hard concerns

No other expanded sections are required for this issue.

---

## Record fields consumed

Required consumed fields:

- `_skills_fit_score`
- `_skills_fit_rationale`
- `_skills_fit_hard_concerns`
- `title`
- `company`
- `location`

Useful behavior notes:

- if `_skills_fit_score` is missing or `null`, render score as `-`
- if rationale is missing, render `-` in rationale mode
- if hard concerns are missing, treat them as empty

The viewer should degrade gracefully when optional fields are absent.

---

## Failure behavior

Exit non-zero if:

- resolved input file does not exist
- neither `--run-date` nor `--input` is provided
- `--limit` is invalid

If the input file exists but contains no records, print a clear warning to stderr and exit successfully.

Per-record robustness:

- malformed JSONL lines should trigger a warning and be skipped rather than crashing the whole viewer
- missing optional fields should not crash rendering

The viewer must remain read-only.

---

## Example usage

Canonical dated run:

```bash
uv run scripts/view_skills_fit_results.py --run-date 2026-05-21
```

Show only the top 20 rows from a run:

```bash
uv run scripts/view_skills_fit_results.py --run-date 2026-05-21 --limit 20
```

Show rationale for the first 10 displayed rows:

```bash
uv run scripts/view_skills_fit_results.py --run-date 2026-05-21 --limit 10 --show-rationale
```

Explicit input override:

```bash
uv run scripts/view_skills_fit_results.py --input data/scored/2026-05-21/skills_fit_scored.jsonl
```

---

## Acceptance criteria

- `uv run scripts/view_skills_fit_results.py --run-date <DATE>` reads the dated scored file successfully
- canonical input resolution uses `data/scored/<DATE>/skills_fit_scored.jsonl`
- `--input PATH` works without `--run-date`
- the viewer fails clearly when neither `--run-date` nor `--input` is provided
- default output shows a readable ranked table
- jobs with hard concerns are clearly flagged
- `--limit` works
- `--show-rationale` works
- malformed JSONL lines warn and skip
- empty scored files produce a clear warning without crashing
- viewer remains read-only and does not mutate input files

---

## Non-goals / future follow-ons

Likely future enhancements, not required for #62:

- score-based filtering
- concern-only filtering
- showing matches, gaps, URLs, or provenance fields
- a Streamlit shortlist browser
- saved reviewer notes or status tracking
- export to CSV/Markdown/email
- dispatch integration

Issue #62 should stay small: a dependable CLI lens over the scored JSONL is enough.
