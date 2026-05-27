# Eval-tooling improvements (Phase G, Track A support)

**Status:** partially completed, still live
**Scope:** reduce manual work in the Phase G calibration and promotion loop
**Track:** B (calibration support), does **not** block A
**Implementation sequence:** three small changes, sequential

______________________________________________________________________

## Motivation

After landing the v5 profile-reframe eval, investigating the "no diff" outcome was harder than it needed to be. The friction has two distinct sources:

1. **Stale docs.** `notes/skills_fit_phase_g/iteration_cycle.md` and `eval_harness.md` document a manual `jq` workflow. Meanwhile `scripts/compare_evals.py --diff <A> <B>` already exists (#44) and does the aggregate-metric side-by-side cleanly. The docs point at the wrong tool.
1. **Real tooling gaps.** Two pieces don't exist regardless of docs:
   - **Per-record diff.** `compare_evals.py --diff` shows aggregate metrics only. For the v5 case, confirming "no records flipped" required manually opening `mismatches_*.jsonl`. No tool reconstructs `gold | A.pred | B.pred` for every record.
   - **Profile snapshots.** `candidate_profile.yml` is gitignored (PII). `runs.jsonl` records `profile_version` + `profile_hash`, but the profile **content** at the time of v5 lives only on the active workstation. Bumping to v6 makes v5 unreproducible.

This spec assumes the current Phase G workflow:

- calibration exploration happens locally or on scratch branches,
- every meaningful experiment is logged,
- PRs are reserved for promotion-worthy winners and structural changes.

## Implementation status

| Change                           | Status  | Notes                                                                                                                                    |
| -------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Change 1: docs + `champions.yml` | Done    | Docs now point to `compare_evals.py`; champion registry lives in `config/eval/champions.yml`.                                            |
| Change 2: per-record diff        | Done    | `compare_evals.py` supports `--against-champion` and `--per-record` for `skills_fit`.                                                    |
| Change 3: profile auto-snapshot  | Done    | `run_skills_fit_eval.py` snapshots `candidate_profile.yml` by `profile_version` before scoring.                                          |
| Next tooling work                | Pending | No additional tooling is defined in this spec yet. Future work should be added as a new change block rather than inferred from old text. |

______________________________________________________________________

## Out of scope (deliberately)

- Pipeline run-ID conventions (data-flow plan's P0.1).
- Eval framework rewrites — extending the existing script, not replacing.
- Holdout splits, multi-reviewer IRR, gold expansion — separate workstreams.
- Storing per-record predictions in `runs.jsonl` directly — not necessary; matched records can be inferred.

______________________________________________________________________

## Decisions (all confirmed)

| Question                  | Decision                                                                                        |
| ------------------------- | ----------------------------------------------------------------------------------------------- |
| Champion run-ID location  | `config/eval/champions.yml` — per-scorer YAML, single canonical source                          |
| `current_state.md`        | Retire entirely                                                                                 |
| Stage 2 scope             | All in — build both Component A and Component B                                                 |
| Profile archive directory | Use existing `config/profile/old_profiles/`, do not create a new `data/eval/profile_snapshots/` |
| Archive trigger           | Auto-snapshot at eval time, not at edit time                                                    |
| Archive filename          | `candidate_profile_<profile_version>.yml` (version strings already have dates baked in)         |
| Hash validation           | Skip for now — single-user workflow, not worth the paranoia                                     |

______________________________________________________________________

## Change 1 — doc refresh + champions.yml (no code)

### New file: `config/eval/champions.yml`

```yaml
# Pinned baseline run-IDs per scorer type. Update via PR when a
# promotion-worthy calibration run establishes new champion metrics
# against the same yardstick (gold set). Gold expansion PRs reset
# entries to null — the next eval run on the new gold establishes
# the next champion.
#
# Run-IDs reference data/eval/runs.jsonl.

skills_fit: phase_r_llm_magnus_20260522_215948_7429
remote_filter: null  # not yet established
```

### Doc edits

1. **`notes/skills_fit_phase_g/iteration_cycle.md`** — replace the `jq` block in step 4 with:

   ```bash
   # Look up the current champion in config/eval/champions.yml, then:
   uv run scripts/compare_evals.py --diff <champion_run_id> <your_new_run_id>
   ```

1. **`notes/skills_fit_phase_g/eval_harness.md`** — same substitution. Also remove the hardcoded run-IDs in "Current reference runs"; replace with a pointer to `config/eval/champions.yml`.

1. **`notes/skills_fit_phase_g/current_state.md`** — delete the file.

1. **`notes/skills_fit_phase_g/README.md`** — remove hardcoded run-IDs from "Current status" (point to champions.yml + runs.jsonl); remove the `current_state.md` entry from the doc map.

1. **`notes/skills_fit_phase_g/governance.md`** — already generic ("the baseline run"); no change needed. Verify on read.

### Acceptance

- `config/eval/champions.yml` exists with `skills_fit` populated.
- All four skills_fit_phase_g docs reference `compare_evals.py --diff` instead of `jq` one-liners.
- The champion run-ID is defined in exactly **one** place (the YAML), referenced from elsewhere.
- `current_state.md` is removed and not referenced by any other doc.

______________________________________________________________________

## Change 2 — Stage 2 Component A: per-record diff

### File: `scripts/compare_evals.py` (extend)

### New flag

`--per-record`, combined with `--diff`. In Change 2, support this for **skills_fit** runs only; other scorer types can keep aggregate-only diff for now. Prints a per-record table after the existing aggregate diff.

### Convenience flag (additive)

`--against-champion <scorer>` resolves the left-hand side of the diff from `config/eval/champions.yml`.

CLI shape:

- `--diff <run_a> <run_b>` — explicit two-run diff
- `--against-champion <scorer> --diff <run_b>` — champion vs one explicit run

Example:

```bash
uv run scripts/compare_evals.py \
  --against-champion skills_fit \
  --diff <your_new_run_id> \
  --per-record
```

### Reconstruction algorithm (no schema change)

Skills-fit gold rows are keyed by full `dedup_hash` and store the human score in `_human_fit_score`. Skills-fit mismatch rows store only the truncated display ID (`record_id == dedup_hash[:8]`). Reconstruct predictions by defaulting every record to `pred == gold`, then overriding from the mismatch file.

```python
def reconstruct_skills_fit_predictions(run_record):
    """Returns ({full_id: pred_score}, {full_id: gold_score}, {full_id: title})."""
    gold_rows = load_jsonl(run_record["gold_file"])
    gold = {r["dedup_hash"]: r["_human_fit_score"] for r in gold_rows}
    titles = {r["dedup_hash"]: r.get("title", "") for r in gold_rows}
    short_to_full = {full_id[:8]: full_id for full_id in gold}

    preds = dict(gold)  # default: matched (pred == gold)
    mismatch_path = run_record.get("mismatch_file")
    if mismatch_path and Path(mismatch_path).exists():
        for m in load_jsonl(mismatch_path):
            full_id = short_to_full[m["record_id"]]
            preds[full_id] = m["pred_score"]
    return preds, gold, titles
```

Two runs → two `preds` dicts keyed by full `dedup_hash` → keyed join on full ID → render the first 8 chars as the display `record_id` in the table.

### Output format

After the existing aggregate diff:

```
  Per-record diff (n=21, sorted by |Δ_A| + |Δ_B| desc)

  record_id  title                          gold  A.pred  B.pred  Δ_A  Δ_B  flipped
  ---------  -----------------------------  ----  ------  ------  ---  ---  -------
  fc321c2c   Staff ML Eng @ ...              5      3       3     -2   -2   no
  3fa06daa   Sr. Software Eng — Applied AI   4      3       3     -1   -1   no
  ...

  Summary: 21 records | 0 flipped | identical predictions on all 21
```

Title truncated to ~28 chars by default. Sort by `|Δ_A| + |Δ_B|` descending.

### Failure modes

- Mismatch file missing on disk → warn, treat as no mismatches.
- Gold files differ between A and B → exit with `"Run A uses gold X, Run B uses gold Y — not comparable"`.
- Either run has `metrics.skipped > 0` → exit with a clear error; without schema changes we cannot safely reconstruct per-record predictions when some rows were skipped.
- Truncated mismatch IDs are ambiguous (two gold rows share the same first 8 chars) → exit with a clear error rather than guessing.
- `--per-record` without `--diff` → clear error.
- `--per-record` on a non-`skills_fit` scorer → clear error for now.
- `--against-champion <scorer>` where scorer is null/missing → clear error pointing at champions.yml.

### Acceptance

- Existing `--diff` aggregate output unchanged.
- Diff between baseline + v5 runs with `--per-record` shows 0 flipped records (matches the manual finding).
- `--against-champion skills_fit --diff <run> --per-record` works end-to-end.
- `--per-record` fails clearly if either run has skipped rows or if the scorer is not `skills_fit`.
- Output is markdown-formatted and useful both for local calibration analysis and PR descriptions.

______________________________________________________________________

## Change 3 — Stage 2 Component B: profile auto-snapshot

### File: `scripts/run_skills_fit_eval.py` (modify)

### Behavior

Right after `profile_version` and `profile_hash` are computed, before the eval loop runs:

```python
old_profiles_dir = Path("config/profile/old_profiles")
old_profiles_dir.mkdir(parents=True, exist_ok=True)
archive_path = old_profiles_dir / f"candidate_profile_{profile_version}.yml"
if not archive_path.exists():
    shutil.copy(PROFILE_PATH, archive_path)
```

Idempotent: skips if archive for this `profile_version` already exists. No hash validation (decided: single-user workflow, would just be noise).

### One-time migration (before the change lands)

Manually snapshot the current v5 profile so it isn't lost when v6 lands:

```bash
cp config/profile/candidate_profile.yml \
   config/profile/old_profiles/candidate_profile_2026-05-22-v5-llm-reframe.yml
```

(v4 — the Phase R baseline profile — was overwritten on disk during v5's edit. Genuinely unrecoverable. Not a fixable-from-now-on gap, just a one-time loss.)

### Verify `.gitignore`

Confirm `config/profile/old_profiles/` is already gitignored (it should be — profile contains PII). If not, add it.

### Optional cleanup

The two existing legacy files (`candidate_profile.yml`, `candidate_profile_b.yml`) under `old_profiles/` should be renamed if their `profile_version` is recoverable, or left as legacy noise. Out of scope for this change — just note it where the work lands.

### Acceptance

1. After running `run_skills_fit_eval.py`, `config/profile/old_profiles/candidate_profile_<profile_version>.yml` exists and matches the in-flight profile.
1. Re-running with the same profile is a no-op (idempotent).
1. The v5 archive exists (`candidate_profile_2026-05-22-v5-llm-reframe.yml`).
1. `.gitignore` blocks accidental commits.
1. `~25 LOC` added to `run_skills_fit_eval.py`.

______________________________________________________________________

## Implementation order

Sequential, three small changes. Each independently shippable. They may land as separate PRs, but that is an implementation choice, not a requirement of the calibration loop.

1. **Change 1 (Stage 1)** — docs + champions.yml. ~15 minutes.
1. **Change 2 (Component A)** — per-record diff. ~2 hours.
1. **Change 3 (Component B)** — auto-snapshot + migration. ~30 minutes.

## Relationship to Phase G workflow

This spec supports the current operating model for `skills_fit`:

- Use local or scratch-branch iteration for most prompt/profile/config exploration.
- Log runs to `data/eval/runs.jsonl` for provenance, including failed or neutral experiments.
- Use `compare_evals.py` to analyze whether a candidate is worth keeping.
- Open a PR only when promoting a winner, updating the champion, or changing the yardstick/infrastructure.

The goal of this tooling is to make disciplined exploration cheap and promotion decisions easier to justify.

## How To Use This Spec

If you are continuing Phase G work:

- Use `notes/skills_fit_phase_g/README.md` for the current operating rules and next recommended action.
- Use this spec only for tooling/support work, not as the source of truth for day-to-day calibration policy.
- Before starting a tooling task, check the implementation-status table above so you do not re-do work that already landed.
