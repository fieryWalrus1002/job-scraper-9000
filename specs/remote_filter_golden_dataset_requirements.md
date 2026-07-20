# Golden Dataset Requirements — Remote Filter Eval

**Date:** 2026-05-14
**Related:** [eval_framework_requirements.md](eval_framework_requirements.md)

______________________________________________________________________

## Purpose

The golden dataset is the ground truth for all remote filter eval runs. Its quality directly determines whether eval metrics are meaningful. This document defines the required structure, target composition, and edge case coverage.

______________________________________________________________________

## Current State

| Metric        | Value                                                                                                  |
| ------------- | ------------------------------------------------------------------------------------------------------ |
| Total records | 50                                                                                                     |
| Pass          | 8 (16%)                                                                                                |
| Trash         | 42 (84%)                                                                                               |
| Source        | Scraped May 2026, legacy teacher/bootstrap + current production proposals, human-reviewed in Streamlit |

**Problem:** 8 positive examples gives a ~±30-point 95% CI on recall. A single FN moves the metric by 12.5 percentage points. Regression detection is not meaningful at this sample size.

______________________________________________________________________

## Target State

| Metric        | Target    |
| ------------- | --------- |
| Total records | ~70       |
| Pass          | ~25 (36%) |
| Trash         | ~45 (64%) |

The target is not artificial balance — it's the minimum positive-class count needed to detect meaningful recall regressions (~±15-point CI). Trash coverage is already sufficient.

______________________________________________________________________

## Record Schema

Every record must have the following fields to be usable in eval:

| Field                   | Required    | Notes                                                                                           |
| ----------------------- | ----------- | ----------------------------------------------------------------------------------------------- |
| `dedup_hash`            | Yes         | Primary key used by `load_gold()` for dedup                                                     |
| `title`                 | Yes         | Used in mismatch reporting                                                                      |
| `company`               | Yes         | Used in mismatch reporting                                                                      |
| `location`              | Yes         | Input to `analyze_remote()`                                                                     |
| `description`           | Yes         | Primary input; records without this are skipped                                                 |
| `source_url`            | Yes         | Required for traceability back to the original posting                                          |
| `_human_verdict`        | Yes         | `"pass"` or `"trash"` — final ground truth                                                      |
| `_human_classification` | Yes         | 3-way eval label: `remote`, `hybrid`, or `onsite`                                               |
| `_human_policy`         | Historical  | Legacy teacher/bootstrap rows may carry historical policy tags; new review rows do not write it |
| `_corrected`            | Yes         | `true` if human overrode the classifier proposal                                                |
| `_filter_metadata`      | Recommended | Captures production classifier prompt hash / commit when the proposal was generated             |
| `_review_metadata`      | Yes         | Captures reviewer prompt hash and commit at review time                                         |
| `search_params`         | Recommended | Provides context to `analyze_remote()` for timezone reasoning                                   |

Records missing `description` are skipped by the eval and waste a slot in the gold set. Invalid `_human_classification` values fail fast.

> **`_human_policy` is a deliberate one-way migration (Phase 32).** The active
> review UI (`src/review_ui/app.py`) writes only `_human_classification`; it does
> **not** write `_human_policy`. Historical rows retain their legacy
> `_human_policy` tags, and both readers tolerate the split: `load_reviewed()`
> falls back to `_human_policy` when `_human_classification` is absent, and
> `scripts/remap_gold_to_4way.py` remains a one-time migration that derives
> `_human_classification` from `_human_policy` for those legacy rows. New gold is
> `_human_classification`-only; there is no back-migration of new rows to the
> legacy field.

______________________________________________________________________

## Edge Case Coverage

The easy cases (obvious onsite, obvious remote) are already well-represented. New records should prioritize the cases where the agent is most likely to err.

### Pass edge cases (agent may incorrectly trash)

| Category                                    | Example Signal                                            | Why It's Hard                                                          |
| ------------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------------------- |
| Remote + non-EST timezone requirement       | "Must overlap PST/CST hours"                              | Agent must accept non-rejected timezones                               |
| Remote + low travel                         | "Quarterly company offsite (~4 days/year)"                | Agent must count days and compare to threshold                         |
| Remote-first with ambiguous office language | "We have an office in SF if you ever want to use it"      | Optional presence ≠ required presence                                  |
| International remote, US-friendly           | "Remote — open to US candidates, no timezone requirement" | Agent must not reject on location alone                                |
| Senior/staff roles with vague travel        | "Some travel may be required"                             | No frequency → agent must decide under uncertainty; policy is `reject` |

### Trash edge cases (agent may incorrectly pass)

| Category                                      | Example Signal                                             | Why It's Hard                                |
| --------------------------------------------- | ---------------------------------------------------------- | -------------------------------------------- |
| EST-only timezone on otherwise remote posting | "Must work Eastern hours"                                  | Job looks fully remote until timezone clause |
| Onsite disguised as remote                    | "Remote-friendly" + "report to NYC office weekly"          | Contradiction buried in description          |
| Hybrid framed as flexible                     | "Mostly remote, 1–2 days in office per month"              | Frequency is low but it's still hybrid       |
| Relocation required                           | "Remote after 90-day onboarding in Austin"                 | Relocation window triggers rejection         |
| Local presence required                       | "Must be within commuting distance of Seattle"             | Not onsite but still location-restricted     |
| High travel remote                            | "Remote with frequent client travel (est. 30–40% of time)" | Travel days exceed threshold                 |

### Ambiguous / unclear — RETIRED (Phase 32)

> **Amended 2026-07-20:** `unclear` was retired to a 3-way axis
> (`remote | hybrid | onsite`) — see `remote_filter_classifier_tuning.md` §2 and
> the Changelog. Postings a reader can't pin down are no longer their own class:
> a named city with no remote language is `onsite`, and genuine zero-signal
> non-jobs (recruiting-spam pages) are dropped from the gold rather than labeled.
> The gold no longer carries `unclear` records.

______________________________________________________________________

## Collection Strategy

1. **Prioritize edge cases over volume.** A new pass record from an easy "fully remote, no requirements" posting adds little. A record from the edge case categories above is worth 5× as much.
1. **Source from the existing scraping pipeline.** Do not construct synthetic records — they won't reflect real job posting language patterns.
1. **Review flow uses production proposals.** Run the production remote filter, sample `remote_filter_classified.jsonl` with `scripts/sample_for_review.py`, then review in Streamlit before adding to `ground_truth.jsonl`. The `_corrected` flag should be set when the human label differs from the classifier proposal.
1. **No re-review of existing records without cause.** If a human review was already done and `_corrected: false`, do not re-litigate it. Only re-review if the policy changes.

______________________________________________________________________

## Out of Scope

- Synthetic or LLM-generated job descriptions
- Records without a real `source_url`
- Records from job categories outside the current search config (data engineering, ML, AI)
