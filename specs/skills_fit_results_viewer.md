# Skills Fit Results Viewer (#62)

## Purpose

Add a lightweight way to inspect ranked skills-fit results after the production runner lands.

This spec covers GitHub issue #62 as a small, focused follow-on to the production runner:

- read scored output from `data/scored/`
- display a ranked shortlist in a human-scannable form
- make `hard_concerns` visible at a glance
- support simple filtering for triage

The goal is not a full application UI. The goal is to let the user answer:

- What are the top-ranked jobs from this run?
- Which high-scoring jobs have blockers or near-blockers?
- Which postings are worth opening first?

---

## Recommended implementation shape

Implement #62 as a **CLI viewer script**, not a new Streamlit app.

Suggested file:

- `scripts/view_skills_fit_results.py`

Why CLI first:

- lower effort than a new web UI
- matches the current repo’s script-driven workflow
- sufficient for issue #62
- avoids duplicating the existing Streamlit review UI, which is for teacher/HITL review rather than scored shortlist browsing

Implementation may use `rich` or similar terminal-formatting helpers, but a plain readable CLI table is sufficient for this issue. Colored score output is optional; the important requirement is a clear `BLOCKERS` flag for hard concerns.

A richer UI can follow later if needed.

---

## Relationship to #61

This viewer reads the output of the production runner spec in `specs/skills_fit_production_runner.md`.

Canonical scored input:

- `data/scored/<DATE>/skills_fit_scored.jsonl`

Legacy fallback scored input:

- `data/scored/skills_fit_scored.jsonl`

The viewer should not compute scores itself. It is strictly a read-only presentation tool.

---

## Scope

### In scope

- Add `scripts/view_skills_fit_results.py`
- Read scored JSONL output
- Print a concise ranked table to the terminal
- Support filtering by score and concern presence
- Support optional expanded rationale/details output
- Work with canonical dated partitions
- Support legacy flat-path fallback

### Out of scope

- New Streamlit app
- Editing or annotating jobs from the viewer
- Re-scoring jobs
- Dispatch/email sending
- Persisting user actions like starred/applied/skipped
- Full-text search UI
- Sorting by arbitrary columns beyond a small practical set

---

## Canonical input resolution

### Canonical mode

When `--run-date YYYY-MM-DD` is provided, and no explicit `--input` is given:

- input: `data/scored/<DATE>/skills_fit_scored.jsonl`

### Legacy compatibility mode

When `--run-date` is omitted, and no explicit `--input` is given:

- input: `data/scored/skills_fit_scored.jsonl`

### Explicit override

If `--input PATH` is provided, it wins over all default resolution.

---

## CLI contract

Suggested arguments:

- `--run-date YYYY-MM-DD`
- `--input PATH`
- `--limit N`
- `--min-score {1,2,3,4,5}`
- `--max-score {1,2,3,4,5}`
- `--only-concerns`
- `--hide-concerns`
- `--show-rationale`
- `--show-matches`
- `--show-gaps`
- `--show-url`

`--show-url` should apply only in expanded detail output, not the compact table view. If URLs are rendered in expanded output, truncate them to a reasonable width by default unless the implementation has a clean wrapped rendering mode.

Minimum useful subset if keeping scope tight:

- `--run-date`
- `--input`
- `--limit`
- `--min-score`
- `--only-concerns`
- `--show-rationale`

Argument validation rules:

- `--only-concerns` and `--hide-concerns` are mutually exclusive; passing both should exit non-zero with a clear error
- if both `--min-score` and `--max-score` are provided, `min` must be less than or equal to `max`
- `--limit` applies **after** filtering, so commands like `--only-concerns --limit 20` return the top 20 matching rows

`--only-concerns` may be combined with score filters. This is intentional: a common use case is to inspect only blocker-flagged jobs among otherwise strong-scoring roles.

---

## Display requirements

### Default table view

Print one row per scored job with columns such as:

- rank
- fit score
- concern flag
- title
- company
- location
- source bucket (`remote_filter_pass` or `local_candidate` if present)

Recommended concern flag behavior:

- blank if no hard concerns
- `BLOCKERS` if `_skills_fit_hard_concerns` is non-empty

### Expanded detail view

When `--show-rationale` is set, print for each displayed job:

- title / company / location
- score
- hard concerns
- top matches
- score rationale
- source URL if present and `--show-url` is enabled

If `--show-gaps` is implemented, also show gaps in expanded mode.

Expanded detail mode is the only place URLs should be shown.

---

## Record fields consumed

The viewer should expect the output shape from the production runner.

Required consumed fields:

- `_skills_fit_score`
- `_skills_fit_rationale`
- `_skills_fit_hard_concerns`
- `_skills_fit_top_matches`
- `title`
- `company`
- `location`
- `source_url` (optional display)

Useful optional fields if present:

- `_skills_fit_gaps`
- `_skills_fit_confidence`
- `_skills_fit_input_source`
- `_skills_fit_metadata`

The viewer should degrade gracefully if optional fields are absent.

---

## Filtering behavior

### Score filtering

- `--min-score 4` should show only strong shortlist candidates
- `--max-score 3` should let the user inspect weaker matches if desired

### Concern filtering

- `--only-concerns` should show only jobs with non-empty `_skills_fit_hard_concerns`
- `--hide-concerns` should show only clean jobs

These flags are especially useful because high fit score and hard blocker can coexist.

---

## Sorting behavior

The viewer should preserve input ordering by default, assuming the scored file is already written in ranked order by #61.

Optionally, the viewer may support simple re-sorting later, but issue #62 does not require that.

The important invariant is that the default view reflects the runner’s ranked output exactly.

---

## Failure behavior

Exit non-zero if:

- resolved input file does not exist
- mutually incompatible flags are provided
- score filter arguments are invalid

If the input file exists but contains no records, the viewer should `log.warning(...)` or print a clear warning to stderr and exit successfully without rendering rows. An empty scored file is unusual and likely indicates an upstream issue, but it is not necessarily a viewer error.

Per-record robustness:

- malformed JSONL lines should trigger a warning and be skipped rather than crashing the whole viewer
- tolerate missing optional fields
- render missing strings as `-` or empty text

The viewer should stay read-only and safe.

---

## Example usage

Canonical dated run:

```bash
uv run scripts/view_skills_fit_results.py --run-date 2026-05-21
```

Show top strong-fit jobs only:

```bash
uv run scripts/view_skills_fit_results.py --run-date 2026-05-21 --min-score 4 --limit 20
```

Show only blocker-flagged jobs with rationale:

```bash
uv run scripts/view_skills_fit_results.py --run-date 2026-05-21 --only-concerns --show-rationale
```

Legacy fallback file:

```bash
uv run scripts/view_skills_fit_results.py
```

---

## Acceptance criteria

- `uv run scripts/view_skills_fit_results.py --run-date <DATE>` reads the dated scored file successfully
- canonical input resolution uses `data/scored/<DATE>/skills_fit_scored.jsonl`
- legacy flat-path fallback still works when `--run-date` is omitted
- default output shows a readable ranked table
- jobs with hard concerns are clearly flagged
- `--min-score` works
- `--show-rationale` works
- `--only-concerns` and `--hide-concerns` are rejected when passed together
- `--limit` is applied after filtering
- empty scored files produce a clear warning without crashing
- viewer remains read-only and does not mutate input files

---

## Non-goals / future follow-ons

Likely future enhancements, not required for #62:

- a Streamlit shortlist browser
- clickable browser-open integration
- saved reviewer notes or status tracking
- export to CSV/Markdown/email
- pairwise reranking display for top-bucket jobs
- dispatch integration

Issue #62 should stay small: a dependable CLI lens over the scored JSONL is enough.
