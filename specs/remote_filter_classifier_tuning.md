# Remote-filter classifier tuning & gold curation (Phase 32)

**Date:** 2026-07-20
**Status:** RATIFIED (2026-07-20). Issues may be derived from the PR-slicing
section.
**Depends on:**

- `remote_filter_taxonomy.md` (RATIFIED 2026-07-17) — defines the (then 4-way)
  axis and the "LLM = pure extractor, judgment in `_gate_user`" principle this
  phase tunes against. **The remap collapse (`onsite_disguised → onsite`,
  `location_restricted → remote`) is ratified there and is not reopened here.**
  **This phase amends it: the axis drops `unclear` → 3-way (§2).**
- `remote_filter_eval_decoupling.md` (Phase 31, shipped) — produced the
  policy-independent categorical metric this phase now iterates on.

**Related specs:** `remote_filter_eval_tuning.md` (stale 2026-05 note; superseded
in spirit by this), `remote_filter_golden_dataset_requirements.md`,
`eval_framework_requirements.md`, `relocation_policy.md`.

**Source:** first live categorical eval run `20260720_155630_14cf`. Detailed
analysis lives in **local-only working notes** (`notes/` is gitignored; the gold set
and eval artifacts are kept local per the gold-locality decision) — not a committed
path. The durable anchor is the run_id, reproducible from `data/eval/runs.jsonl`.

______________________________________________________________________

## Objective

Phase 31 made the eval **measure the right thing** (the LLM classifier, on a
policy-independent 4-way axis). This phase acts on what the first honest run
revealed: curate the gold so the metric is trustworthy, tune the classifier
prompt against the one systematic error, fix a blind travel metric, and only then
pin a champion baseline. This is the eval-driven quality loop the decoupling was
built to enable — the red/green after the harness.

______________________________________________________________________

## Baseline (run `20260720_155630_14cf`, 104 records)

| Metric           | Value                             |
| ---------------- | --------------------------------- |
| Micro accuracy   | **0.9327** (7 mismatches)         |
| Macro P / R / F1 | 0.7023 / 0.7176 / 0.7095          |
| Travel MAE       | 0.0000 (n=2 — near-blind, see §4) |

Per-class: `remote` 0.92/0.94 · `hybrid` 0.93/1.00 · `onsite` 0.96/0.93 ·
`unclear` **0.00/0.00 (support=1)**.

The 93% micro number is healthy. Macro F1 (0.71) is an artifact of the degenerate
`unclear` class (support=1) and is not a capability read — this phase **retires
`unclear`** (§2), which removes that artifact at the root. Five of the seven
mismatches are gold/metric problems, not classifier problems.

______________________________________________________________________

## Problem: the harness works; the inputs to it don't yet

Five distinct issues, each a workstream below.

1. **Gold carries teacher policy-tag mislabels** that flow — correctly — through a
   taxonomy-faithful remap into wrong 4-way labels. Not a code bug; a HITL
   re-ratification gap. **Root cause = the teacher-prompt drift below.**
1. **Teacher-prompt taxonomy drift.** The student/production prompt
   (`prompts/remote_agent/system_prompt.txt`) was migrated to the ratified 4-way
   axis in Phase 30, but the **teacher prompt**
   (`prompts/remote_agent_teacher/system_prompt.txt`) — which *proposes the gold
   labels* — still emits the old **8-way** fine-grained enum (`fully_remote | remote_with_*_travel | onsite_disguised | location_restricted | …`). That stale
   taxonomy is the upstream source of the mislabels in item 1
   (`onsite_disguised` dumping-ground, `location_restricted` misuse). The
   fine-grained `_human_policy` it produces is **not load-bearing**: only
   `src/review_ui/app.py` reads it; the gate (`_gate_user`) reads
   `remote_classification` + `acceptable_classifications`, never `_human_policy`.
   The teacher bootstrap was a cold-start tool from before the pipeline worked.
   **Retire it — propose gold from the production pipeline instead (§2b).**
1. **`unclear` is not a real classification** — it conflates "posting states no
   location" (rare; almost always spam/stub → a prefilter/data-quality concern)
   with "model is unsure" (a hedge the taxonomy already forbids). It is degenerate
   in the eval (support=1) and its original job — surfacing borderline cases — is
   now a **gate/UX** concern after the Phase 31 decoupling, not a classifier
   label. **Retire it → 3-way axis.**
1. **Search-provenance `workplace_filter=remote` is over-weighted** by the
   classifier — the one *systematic* classifier error (3 of 4 false-`remote`s).
1. **Travel MAE is structurally blind** (inner-join over a gold field populated on
   3 of 104 rows).

Items 2 + 3 are one coherent change (reconcile every prompt/axis to 3-way); §2
covers both. Only after items 1, 2, 3, 5 are addressed is a champion baseline (§5)
meaningful.

______________________________________________________________________

## 1. Gold curation: re-ratify mislabeled policy tags

The remap table is **correct** — it implements the ratified taxonomy. The
disputed golds are cases where the teacher's `_human_policy` is wrong *for the
posting*, so the correct mapping yields a wrong 4-way label. Fix at the label
layer (HITL), not the mapping layer.

| record     | `_human_policy` (disputed)    | should be              | model said | why the tag is wrong                                                                                                 |
| ---------- | ----------------------------- | ---------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------- |
| `6bd6d837` | `onsite_disguised`            | `hybrid`               | hybrid     | body offers *"WFH or office hub"* + commuting distance — a genuine hybrid, not fake-remote-that-is-onsite            |
| `d9d43e48` | `location_restricted`         | `onsite`               | onsite     | *"client in Saint Louis, MO,"* zero remote language; `location_restricted` means *genuinely remote, geo-gated*       |
| `62ae121f` | `remote_with_frequent_travel` | `onsite` (contestable) | onsite     | requires *"residence within ~45 min of an SEL office"* + reporting to a local office; base arrangement is not remote |
| `e4d46ee7` | *(review)*                    | ?                      | remote     | US-only + "flexible culture" + quarterly offsites, no onsite language; half classifier over-weighting (§3)           |

**Action:** re-read each body, correct `_human_policy`, let the existing remap
re-derive `_human_classification`. `62ae121f`/`e4d46ee7` are genuine boundary
calls — ratify or annotate why gold stands. Record pre/post label diffs alongside
the gold (local-only, since the gold set is local; promote to a committed doc such
as `data/eval/edge-cases.md` if/when the gold is genericized and committed).

These 3 legacy mislabels still need a one-time HITL fix (they are already in gold),
but the *recurrence* is prevented at source by retiring the teacher bootstrap (§2b):
once gold is proposed by the production classifier on the 3-way axis, there is no
`onsite_disguised` / `location_restricted` dumping-ground to refill.

______________________________________________________________________

## 2. Reconcile every prompt/axis to 3-way (retire `unclear` + fix teacher drift)

One coherent change: make the **teacher prompt, student prompt, gold, and metric**
all agree on the target axis **3-way — `remote | hybrid | onsite`**. Two threads:

### 2a. Retire `unclear`

**Decision (ratified 2026-07-20):** `unclear` is retired everywhere — gold label,
model output, and metric. Rationale (Problem §3): as the labeler you always know the
real class or the posting isn't a classifiable job; "surface borderline" is now a
gate concern post-decoupling; and `unclear` only ever produced a degenerate class
and a mislabel sink. **Supersedes the earlier "expand `unclear`" plan** — removing
the class kills the macro-F1 instability at the root instead of papering over it.

### 2b. Retire the teacher bootstrap; propose gold from the production pipeline

**Decision (ratified 2026-07-20):** the teacher-student **bootstrap framework** is
retired. It was a cold-start tool for building a gold set before a working pipeline
existed; now `run-overnight` produces classified jobs with the real
`RemoteFilterInput` (production-fidelity input, better than the bootstrap ever had).

New gold-growth flow: **sample records from live pipeline runs → the production
classifier (`gpt-5.4-mini`, per `config/agent/remote_agent.yml`) proposes the 3-way
label + structured fields → human ratifies in the review UI (HITL stays).** The
model works well and the human review is the backstop. This permanently kills the
teacher/student taxonomy drift (Problem §2) — there is no second prompt left to go
stale.

Retire:

- `prompts/remote_agent_teacher/` (the stale 8-way teacher prompt),
- `scripts/prepare_batch.py` + `scripts/merge_batch_results.py` (OpenAI Batch
  bootstrap plumbing).

Keep: the review UI (`src/review_ui/app.py`) and `sample_for_review.py`-style
sampling; `remap_gold_to_4way.py` as a **one-time legacy-migration tool** only
(historical gold has fine-grained `_human_policy`; new records are 3-way at source).
`_human_policy` becomes the 3-way class (or is renamed/retired) — the review UI
(lines ~68/99) reads/writes it, update that field. Amends
`remote_filter_golden_dataset_requirements.md`.

> **Known limitation (documented, accepted):** proposing from the *same* model the
> eval scores is mildly circular — automation bias can let the model's **systematic**
> errors (e.g. the §3 search-provenance over-weighting) get ratified into gold. This
> is why gold review is not the only error-discovery path: **mismatch review**
> (independent human judgment on where model ≠ gold) remains the primary way
> systematic errors surface, and a periodic **blind spot-check** of a gold sample is
> the cheap mitigation. Revisit an independent/stronger proposer if drift in accuracy
> is ever suspected.

### Shared retirement/reconciliation touchpoints (implementing slice)

- `RemoteClassification` `Literal` + `REMOTE_CLASSIFICATIONS` — drop `unclear`.
  Keep it a *superset* only if stored historical data still contains it (mirror the
  Phase 14 travel-enum precedent); otherwise remove outright.
- **Student** prompt — remove the `unclear` option + its "no location/policy"
  instruction; keep the "named city → onsite" default that absorbs would-be
  `unclear` cases.
- **Teacher** prompt + bootstrap scripts — **deleted**, not migrated (§2b).
- `_gate_user` `acceptable_classifications` + config defaults — drop `unclear`.
- Categorical metric label list (`run_remote_filter_eval.py` / `metrics.py`) —
  3 labels; confusion matrix 3×3.
- Review UI (`src/review_ui/app.py`) — `_human_policy` field follows the axis change.
- Gold: retag the **1** existing `unclear` record (`2c713280`, SynergisticIT
  recruiting post) — either to its real 3-way class or **out of the remote-filter
  gold** if it's a non-job (preferred; see prerequisite).

**Prerequisite — checked 2026-07-20.** The concern was that zero-signal non-jobs
would have no honest home once `unclear` is gone. Finding: `src/prefilter/`
(deterministic rules router, *not* `src/agents/prefilter/` — CLAUDE.md path is
stale) does **not** drop them — it rejects non-US / banned-term / then routes
"remote or **ambiguous**" to `remote_filter_candidate`, so signal-less US posts are
*forwarded* to the classifier by design. **That's acceptable:** the real safety net
is the taxonomy's **named-city → onsite** rule — most zero-signal posts still carry
a location (`2c713280` = "New York, NY" → `onsite`), which is an honest 3-way home.
The genuinely locationless residual is rare and handled by the `banned_anywhere`
blocklist in `config/agent/prefilter.yml` (existing pattern; add specific
staffing/recruiting mills as they surface). So retiring `unclear` is viable without
a prefilter change; the gate is "does a zero-signal post get an honest 3-way label"
(yes), not "does the prefilter drop it" (no, by design).

- **Travel labels (populated on 3/104 rows):** hand-fill `_human_travel_days` on
  the rows with travel language in the body — the 8 "gold-None → pred-number" rows
  are the review shortlist (the model already flagged travel; ratify or reject
  each). Travel is not gated, so this feeds §4's metric, not classification.

______________________________________________________________________

## 3. Classifier tuning: down-weight search-provenance

The one systematic classifier error. The prompt's search-provenance note tells the
model to treat `workplace_filter=remote` as *"weak but relevant evidence… unless
contradicted."* The model promotes body-silence to a confident `remote`: 3 of the
4 false-`remote`s (`07209122`, `e4d46ee7`, `2c713280`) lean explicitly on it.
(`2c713280` is the retired-`unclear` record from §2 — once it's retagged/removed,
this reduces to the `07209122`/`e4d46ee7` pattern, but the lever is the same.)

**Action:** revise `prompts/remote_agent/system_prompt.txt` so `workplace_filter=remote`
cannot by itself promote a policy-silent body to `remote` — require a
corroborating body signal, or down-rank the provenance note explicitly. Measure
the before/after delta **against re-ratified gold** (§1) so the change isn't
scored on dirty labels. This is the precision lever for **#16**.

______________________________________________________________________

## 4. Travel metric: report coverage, not just inner-join MAE

`travel_mae`/`travel_n` inner-joins gold∩pred, so it silently drops every
asymmetric row: on this run, 1 miss (gold=187→None) and 8 spurious/unscored
(gold=None→number) vanished, leaving n=2. The metric can't see the field the
classifier is most active on.

**Action (after §2 gives travel real support):** alongside MAE, report
**coverage** (of gold-travel rows, fraction the model populated + closeness) and
**spurious rate** (of model travel numbers, fraction landing on gold-None rows).
Until gold travel has support, keep `travel_mae`/`travel_n` **out of any baseline
snapshot**. Small metrics change in `src/agent_eval/metrics.py` +
`run_remote_filter_eval.py` assembly.

______________________________________________________________________

## 5. Pin the champion baseline

Once §1, §2, §4 land, re-run the eval and snapshot the champion for regression
comparison. This is **#63**, which was blocked on having a policy-independent metric
(now shipped) and clean gold (§1/§2).

**Metric of record (decided 2026-07-20): micro accuracy + `remote` recall.** Micro
accuracy is the headline (robust to the remaining `hybrid`/`onsite` class
imbalance); `remote` recall is the guard on the costly "silently drop a good job"
error; the full 3×3 confusion matrix is tracked alongside. Macro F1 is a **secondary
watch** only — interpretable now that `unclear` is gone, but still weight-sensitive
to the smaller `hybrid` class, so not the headline scalar. (Rationale in local-only
working notes; `notes/` is gitignored.)

## 6. Multi-model comparison tooling

Model swapping already works (`--provider`/`--model`/`--temperature`, SC-3) and each
run self-describes its `config.model` + full categorical `metrics` in
`data/eval/runs.jsonl` — so a champion/challenger sweep across N models (local LLM,
`gpt-5.4-mini`, `gpt-4o-mini`, DeepSeek, …) is already *capturable*. The gap is the
comparator: `scripts/compare_evals.py` only knows the **binary** and **ordinal
(skills_fit)** metric families; its `detect_eval_type` doesn't match the categorical
run record (`micro_accuracy` / `macro_f1` / `per_class` / `confusion`), so
categorical runs fall through.

**Action:** add a **categorical family** to `compare_evals.py` — detect on
`micro_accuracy`, render the metric-of-record columns (micro accuracy, `remote`
recall, macro F1) and support `--diff <run_a> <run_b>` across models. This makes the
N-model comparison a one-liner instead of a hand-rolled `jq`, and is the mechanism
that pins the champion in §5. Small, self-contained; no gold or prompt dependency.

______________________________________________________________________

## PR-slicing (draft — file issues only after ratification)

1. **Gold policy-tag re-ratification** (§1) — HITL; correct `_human_policy` on the
   4 disputed rows, re-run remap, log diffs. No production code. Prereq for §5's
   provenance work.
1. **Reconcile axis to 3-way** (§2a + §2b) — (2a) drop `unclear` from
   `Literal`/metric/student-prompt/gate; retag the 1 `unclear` gold record;
   **verify prefilter catches zero-signal non-jobs first** (gates the slice).
   (2b) **retire the teacher bootstrap** — delete `prompts/remote_agent_teacher/`,
   `prepare_batch.py`, `merge_batch_results.py`; gold now proposed by the production
   classifier over live pipeline records, human-ratified; `remap_gold_to_4way.py`
   demoted to legacy-only; review-UI `_human_policy` follows the axis. Amends
   `remote_filter_taxonomy.md` + `remote_filter_golden_dataset_requirements.md` (+
   the CLAUDE.md teacher-first note, remote_filter-only). Bump eval `schema_version`.
   *(Splittable into 2a unclear / 2b bootstrap-retirement if the diff is large.)*
1. **Travel label fill** (§2) — hand-ratify `_human_travel_days` on the review
   shortlist. Independent of 1/2.
1. **Travel metric: coverage + spurious-rate** (§4) — `metrics.py` +
   eval-assembly; bump eval `schema_version`. Depends on 3 for meaningful numbers.
1. **Classifier prompt: down-weight provenance** (§3) — prompt edit + before/after
   eval. Depends on 1. Closes/advances **#16**.
1. **Categorical comparison in `compare_evals.py`** (§6) — add the categorical
   metric family (detect `micro_accuracy`; render micro accuracy + `remote` recall +
   macro F1; `--diff` across models). Independent; unblocks multi-model champion/
   challenger. Feeds §5 / **#63**.
1. **Pin champion baseline** (§5) — snapshot micro accuracy + `remote` recall +
   3×3 confusion. Depends on 1, 2, 4, and the §6 comparator. Closes **#63**.

______________________________________________________________________

## Related open issues

- **#16 — tune remote-filter precision to ≥0.80.** The provenance over-weighting
  (§3) is the concrete lever; re-milestone here.
- **#63 — establish baseline and pin champion.** Unblocked by Phase 31; §5
  delivers it. Re-milestone here.

______________________________________________________________________

## Resolved decisions (2026-07-20)

1. **Champion metric of record (#63): micro accuracy + `remote` recall**, with the
   3×3 confusion matrix tracked and macro F1 as a secondary watch (see §5).
1. **`unclear` retired → 3-way axis** (§2a).
1. **Teacher bootstrap retired; gold proposed by the production classifier
   (`gpt-5.4-mini`) over live pipeline records, human-ratified** (§2b). Circularity
   accepted as a documented limitation, mitigated by mismatch review + blind
   spot-checks.

## Open questions

1. **`62ae121f` / `e4d46ee7`:** ratify the flips, or keep gold and annotate? A
   per-record HITL call resolved *during* slice 1 (re-read the body at relabel
   time) — defines where the remote/onsite boundary sits for field roles and
   geo-restricted remote. Not blocking ratification.

______________________________________________________________________

## Changelog

- **2026-07-20 — draft.** Promoted from `notes/remote_filter_eval_2/`
  findings after the first live categorical run (`20260720_155630_14cf`).
  Corrected an initial mis-read that the disputed golds were remap-table
  mappings: the remap is faithful to the ratified taxonomy, and the disputes are
  teacher policy-tag mislabels (HITL re-ratification), not code fixes.
- **2026-07-20 — retire `unclear` → 3-way axis.** Decision ratified. §2 flipped
  from "expand `unclear`" to "retire it": the class conflated extraction-silence
  (a prefilter concern) with model uncertainty (a forbidden hedge), was degenerate
  in the eval, and its "surface borderline" purpose is now a gate concern after the
  Phase 31 decoupling. Axis is now `remote | hybrid | onsite`. Amends the ratified
  `remote_filter_taxonomy.md` (implementing PR updates its changelog). Added a
  prefilter-coverage prerequisite gating the slice.
- **2026-07-20 — teacher-prompt drift found; bootstrap retired.** Review surfaced
  that the student prompt is 4-way but the teacher prompt still emits the legacy
  8-way enum — the upstream source of the §1 gold mislabels. `_human_policy`
  confirmed non-load-bearing (only the review UI reads it). Decided to **retire the
  teacher-student bootstrap entirely** (a cold-start artifact) rather than reconcile
  it: gold is now proposed by the production classifier (`gpt-5.4-mini`) over live
  pipeline records and human-ratified. Circularity documented + mitigated. §2b
  rewritten accordingly.
- **2026-07-20 — RATIFIED.** Champion metric (micro accuracy + `remote` recall),
  `unclear` retirement, and teacher-bootstrap retirement resolved. Issues may now
  be filed from PR-slicing.
- **2026-07-20 — multi-model comparison slice added (§6).** Confirmed model swap is
  CLI-driven and `config.model` + categorical `metrics` are tracked per run, but
  `compare_evals.py` doesn't yet recognize the categorical metric family. Added a
  slice to close that so champion/challenger across N models is a one-liner.
