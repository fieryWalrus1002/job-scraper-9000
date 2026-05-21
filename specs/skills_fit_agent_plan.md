# Skills Fit Agent Plan

## Purpose

Implement Phase 3 of the pipeline: score remote-filtered jobs against the candidate profile so the dispatcher (Phase 4) has a ranked shortlist to deliver.

This plan supersedes the earlier 0–100 fit-score draft. Two things changed from that version:

1. **Score is ordinal 1–5, not continuous 0–100.** LLMs don't produce calibrated scalar scores. The 0–100 layer was theatre on top of what the model was actually doing (sorting into 4–5 bands). We make the band *be* the score and stop pretending precision exists where it doesn't.
2. **Eval-forward sequencing.** No production runner code lands before the eval harness is roughed out. Schema → metrics → seed gold set → eval driver, *then* prompt and tuning, *then* productionize the runner. Red/green/refactor for agents.

---

## Pipeline position

```text
data/filtered/<DATE>/remote_filter_pass.jsonl
  → skills_fit
  → data/scored/<DATE>/skills_fit_scored.jsonl
  → dispatch / shortlist UI
```

---

## Schema

```python
# src/agents/skills_fit/models.py

SCHEMA_VERSION = "1.0.0"

FitScore = Literal[1, 2, 3, 4, 5]
Confidence = Literal["low", "medium", "high"]

class SkillsFitAnalysis(BaseModel):
    fit_score: FitScore = Field(
        description=(
            "1 = reject; 2 = weak fit; 3 = possible fit; "
            "4 = good fit; 5 = strong fit. "
            "Authoritative band definitions live in the system prompt and the Calibration section of this plan."
        )
    )
    confidence: Confidence = Field(
        description=(
            "How confident the model is that the posting contains enough reliable information to judge the fit. "
            "low = vague/contradictory JD; high = clear and specific."
        )
    )
    score_rationale: str = Field(
        description=(
            "Concise evidence-based explanation of the score. "
            "Identify the core matches, material gaps, and why this score band was chosen. "
            "Not a step-by-step CoT — an auditable summary suitable for the review UI and mismatch logs."
        )
    )
    top_matches: list[str] = Field(
        default_factory=list,
        description="2–5 specific overlaps between the posting and the candidate profile (skills, domain, level)."
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="2–5 missing requirements, weak matches, or role misalignments. Required for scores 1–4."
    )
    hard_concerns: list[str] = Field(
        default_factory=list,
        description=(
            "Hard or near-hard blockers — clearance, location, credential, seniority, salary, "
            "work authorization, contract type. Dispatcher uses this to filter/flag even high-scoring matches."
        )
    )
```

**No `verdict` field.** `fit_score` is the verdict. The rubric lives in the prompt, anchored with concrete band descriptions and `_human_notes` examples lifted verbatim from the gold set.

**Why `score_rationale` and not `reasoning_trace`** (the name used in `remote_filter/models.py`): we want an auditable summary the reviewer can scan in the UI, not hidden step-by-step CoT. The naming inconsistency with the remote-filter agent is acknowledged tech debt — eventually align both names; not in this PR.

**Why `confidence` but not `ambiguity_notes`:** scraped JDs vary wildly in quality. A `fit_score=3` from a precise JD is different from a `fit_score=3` from a vague recruiter-spam posting; the eval should be able to slice on that. `confidence` is cheap (one Literal). `ambiguity_notes` overlaps with `score_rationale` and adds another freeform list that's hard to evaluate — skip for v1.

**`hard_concerns` is independent of `fit_score`.** A `fit_score=4` with `hard_concerns=["requires active TS/SCI clearance"]` is genuinely different from a clean 4 — the dispatcher needs to route them differently. Don't collapse blockers into the score.

**No per-axis sub-scores in v1.** Tempting (`tech_score`, `level_score`, `domain_score`), but YAGNI until we see whether 1–5 ordering produces a useful shortlist. Add only if intra-band sort becomes a real problem.

---

## Metrics

The remote-filter eval is binary, so confusion-matrix metrics (accuracy/precision/recall/F1) work. Skills-fit is ordinal *and* the product is a top-N shortlist — neither set of metrics alone tells the whole story. We need both ordinal-agreement metrics and top-of-list metrics.

**Ordinal agreement** — does the model agree with the human on a per-record basis?

| Metric | Definition | Why it matters |
| --- | --- | --- |
| `exact_match_acc` | `% of preds where pred == gold` | Strict agreement; sanity check |
| `off_by_one_acc` | `% of preds where abs(pred - gold) <= 1` | Tolerant agreement; catches "right neighborhood" |
| `mae` | mean of `abs(pred - gold)` | Average score error in band units |
| `bias` | mean of `(pred - gold)` | Is the model systematically high/low? |
| `spearman_rho` | Spearman rank correlation between pred and gold | Rank fidelity across the whole gold; biased models can still rank well |
| `confusion_5x5` | full 5×5 matrix | Where the off-by-twos happen — diagnostic, not headline |

**Top-of-list quality** — would the dispatcher's actual shortlist be worth applying to?

| Metric | Definition | Why it matters |
| --- | --- | --- |
| `precision_at_5` | `% of pred-top-5 with gold >= 4` | Of the jobs the agent would show first, how many are actually good? |
| `precision_at_10` | `% of pred-top-10 with gold >= 4` | Same, wider window |
| `mean_gold_score_at_top_10` | mean gold score of the pred-top-10 | Absolute quality of the shortlist, not just precision |
| `top_bucket_purity` | `% of pred-5s where gold >= 4` | Does "the agent thinks it's a 5" actually correspond to a strong job? |

`precision_at_k` is the application-decision metric — it maps directly to the daily-application bandwidth constraint. `spearman_rho` is the per-record rank-fidelity metric. Both matter; neither is sufficient alone.

A model with Spearman ρ = 0.85 but `precision_at_5` = 0.4 is scrambling the top of the list while looking fine in aggregate — that's the failure mode the top-k metrics catch. **Optimize for both; prioritize `precision_at_k` when they disagree** — the product mission is application-decision quality at the top of the ranked list, not aggregate rank agreement.

These land in `src/agent_eval/metrics.py` as `compute_ordinal_metrics(preds, golds)` alongside the existing `compute_metrics()`. The eval driver picks which to call. `precision_at_k` takes a `positive_threshold` parameter (default 4) — different thresholds answer different questions, so `runs.jsonl` records which was used.

### Eval coverage of non-`fit_score` fields

`fit_score` gets full ordinal evaluation. The other schema fields are harder to evaluate against gold and need a per-field decision:

| Field | Evaluation approach |
| --- | --- |
| `fit_score` | Full ordinal + top-k metrics (above) |
| `confidence` | Agreement % vs `_human_confidence`; diagnostic, not headline |
| `score_rationale` | Spot-check only in mismatch reviews; no automated metric |
| `top_matches`, `gaps`, `hard_concerns` | TBD — see Open Question 4 |

---

## Calibration: the laundry-list problem

Job descriptions are aspirational, not literal requirements. A typical posting lists 8–15 skills; strong candidates routinely match 50–70% of them. If we treat the JD as ground truth — "candidate has X of N listed skills" — every real, hireable role caps out at a 2 or 3. Every score collapses to the middle and the eval looks broken even when the model is doing exactly what we asked.

This is the central calibration problem in job matching. The 1–5 scale only means something if the model interprets "fit" the way a hiring manager would, not the way an over-literal recruiter checklist would. Three things follow.

### Rubric: anchor on "core requirements," not "% match"

The 1–5 bands describe coverage of *core* requirements, not line-by-line JD overlap. The word "core" does the heavy lifting and the model has to infer it from context — which is exactly where mistakes happen, so we anchor it with in-prompt examples drawn from the gold set.

Expanded bands (this table is authoritative; the Pydantic field doc is the abbreviated version):

| Score | Meaning |
| --- | --- |
| 5 | Core stack matches strongly. Level and domain aligned. Gaps only in nice-to-haves. |
| 4 | Core stack matches. Level/domain aligned. Some non-trivial gaps the candidate could close on the job. |
| 3 | Partial core match, OR aligned but in a stretched-adjacent domain. Real concerns alongside real matches. |
| 2 | Core requirements largely missing, OR fundamental mismatch on level. |
| 1 | Wrong kind of job entirely — different domain, different career track, hard disqualifier. |

### The keyword-bait counterpart

JD aspirationality runs in both directions. Laundry-list inflates the listed *requirements* (over-states the bar). **Keyword bait** inflates the listed *skills* (over-states what the job actually involves). A posting saying "Experience with C++, Python, ML, cloud, Kubernetes preferred" could be a real ML infrastructure role or a generic IT support job with buzzwords pasted in. Read literally, both inflate the model's apparent match.

The prompt should instruct the model to classify each mentioned skill or requirement by its role in the posting:

| Role in posting | Weight |
| --- | --- |
| Core responsibility — what the person actually does day-to-day | Heavy |
| Required qualification — listed as a gate (years, credential, level) | Heavy if material |
| Preferred / nice-to-have — wishlist | Light; gaps acceptable for 4–5 |
| Incidental keyword — mentioned in passing, tangential | Near-zero |
| Company tech-stack decoration — "we use X internally" | Near-zero |

A candidate matching 3 of 5 *core responsibility* signals scores higher than one matching 8 of 10 *preferred / decoration* signals, even though the raw overlap count is lower. The system prompt and the gold-set notes both need to make this distinction explicit.

### System prompt: state the realism floor explicitly

The system prompt must contain a calibration paragraph telling the model that JD coverage is not the scoring axis, in both directions. Draft language:

> Job descriptions are aspirational in two directions. They (a) over-list requirements — a strong candidate typically matches 50–70% of listed skills, not 100% — and (b) over-mention skills that aren't core to the actual role (keyword bait, company tech-stack decoration). Before scoring, classify each mentioned skill or requirement as core responsibility, required qualification, preferred/nice-to-have, incidental keyword, or stack decoration. Weight matches and gaps accordingly. A score of 4–5 requires matching the **core** requirements with relevant adjacent experience; gaps on nice-to-haves or decoration do not lower the score. A 3 means real concerns on core requirements alongside real matches — not "matched 60% of the laundry list."

Without this paragraph, the model defaults to literal-checklist reasoning and the entire eval collapses to the 2–3 band.

### Gold-set notes are the actual calibration mechanism

When hand-scoring the seed (Phase R) and reviewing teacher-batch outputs (Phase G), capture in `_human_notes` *which* gaps were material vs which were JD-bloat. Example:

> "JD lists Kubernetes, AWS, GCP, Docker, Terraform, Pulumi. I have Docker + AWS. Scored 4 because the actual job is 'build ML serving infra' and containerization is the core need — the cloud-provider sprawl is just JD bloat. The K8s gap is real but learnable."

These notes are not commentary — they become the in-prompt examples that anchor the model's calibration. **The notes are what actually calibrates the agent**, more than any band description does. Treat their quality as a first-class concern of the gold set, not as optional metadata.

### Where this connects to Variant A

The embedding-evidence variant (under "Operation: Smoosh, and what comes after") gets more compelling once we know how the model handles laundry-list JDs. Structured overlap evidence — "candidate matches 4 of 12 JD skills, those 4 are X Y Z W, weighted by frequency-in-posting" — lets the model reason explicitly about *which* matches happened, not just how many. That makes the calibration prompt more grounded. Still: defer the experiment until Phase G mismatch analysis confirms "model treated JD as a literal checklist" is a real failure mode in the runs.

---

## Prerequisite: land issue 25 first

`src/utils/batch_api.py` (issue 25) must land before the skills-fit eval driver. The skills-fit eval will use the OpenAI Batch API for cheap iteration (50% off, fine for offline scoring of dozens of records). Adding a fourth duplicate copy of the batch plumbing is the moment to refactor — not after.

**Issue 25 scope stays strict:** extract the 4 primitives (`upload_and_create_batch`, `poll_until_done`, `download_results`, `TERMINAL_STATUSES`), refactor the 3 existing callers, ship. Do not expand it to include skills-fit code.

After #25 is merged, skills-fit can import from `utils.batch_api` cleanly.

---

## Sequencing: red → green → refactor

### Phase R (Red) — eval harness + intentionally weak scorer

**Branch:** `feature/skills-fit-eval`

Land these in order, in one PR if small enough:

1. **`src/agents/skills_fit/models.py`** — `SkillsFitAnalysis` Pydantic model and `SCHEMA_VERSION`. No runner code yet.
2. **`src/agent_eval/metrics.py`** — add `compute_ordinal_metrics(preds: list[int], golds: list[int]) -> dict`. Unit tests with hand-built cases (perfect agreement, all-off-by-one, all-bias-+1, random).
3. **Seed gold set** — hand-score 25 jobs **stratified across all five bands**, not randomly sampled. Target distribution:

   | Count | Type |
   | --- | --- |
   | 5 | obvious 5s — clean strong fits |
   | 5 | obvious 4s — solid fits with manageable gaps |
   | 5 | ambiguous 3s — partial core match or stretched-adjacent domain |
   | 5 | **deceptive 2s** — mention the candidate's stack but mismatch on level, credential, domain, or role type |
   | 5 | hard-reject 1s — wrong kind of job entirely |

   The deceptive 2s are the most important category and the easiest to miss with random sampling. Examples: a C++ role that's embedded automotive requiring AUTOSAR; a Python role that's mostly data-labeling ops; an ML role with a PhD research-scientist requirement; a "remote" role that's remote-within-Canada-only.

   Format mirrors the remote-filter gold, with the v1 schema fields:
   ```json
   {"dedup_hash": "...", "title": "...", "company": "...", "description": "...",
    "_human_fit_score": 4, "_human_confidence": "high",
    "_human_top_matches": [...], "_human_gaps": [...], "_human_hard_concerns": [...],
    "_human_notes": "..."}
   ```
   Lives at `data/eval/skills_fit_ground_truth.jsonl`. Gitignored like the remote-filter gold.

   Why hand-score and not teacher-batch yet: the seed defines *the rubric*. If you teacher-batch first, you're calibrating to the teacher's defaults, not your preferences. Score these yourself so your judgment anchors the gold.

   **Teacher-first HITL alternative.** Cold single-rater labeling exhibits calibration drift across 25+ records — a known issue in NLP labeling work, standardly mitigated by rater calibration via teacher proposals. The specific symptom that motivates the switch here: JDs use aspirational "required" / "preferred" / "experience with" phrasing, and a literal-reading reviewer consistently over-rejects (the laundry-list problem from the labeler's side — the rubric in the system prompt tells the *model* not to read JDs literally, but the human seed-labeler is doing exactly that and the prompt does nothing for them). In the teacher-first variant, a frontier model proposes labels, the human reviews and either ratifies or flips, and notes are *especially* load-bearing on flips (the disagreements become the prompt's calibration anchors). This trades the "score yourself first" calibration anchoring for label quality and consistency; choose based on the reviewer, not as the default. Discipline guardrails: anti-rubber-stamping (skip the record when uncertain rather than accept the teacher), notes mandatory on every saved record, teacher fields preserved in the gold output for audit trail. The external reviewer pipeline below adds a further check for HR-domain knowledge gaps that the teacher and reviewer might share.

   **Notes discipline:** `_human_notes` is mandatory, not optional. Each record's note should explain which gaps were material vs JD-bloat, and which mentioned skills were core responsibility vs decoration — these notes become the prompt's in-context examples in Phase G. See "Calibration: the laundry-list problem" above.

   **External reviewer pipeline (optional but recommended).** For reviewers with limited HR-domain literacy, recruit a small panel (2–3 people) to spot-check a subset of the scored gold. The subset is targeted, not random: include (a) records where the human flipped the teacher's proposal — highest-signal disagreements, (b) the borderline bands (3s and deceptive 2s), and (c) 1–2 anchor cases per band as sanity checks. Reviewers don't see the teacher's proposal; they score independently. JSONL gold accumulates `_teacher_*`, `_human_*`, and `_consultant_*` field groups for a full audit trail. The reviewer-facing artifact (markdown doc, sheet, etc.) is a downstream rendering choice — JSONL stays the source of truth.

4. **`scripts/run_skills_fit_eval.py`** — mirrors `run_remote_filter_eval.py`. Loads gold, calls `analyze_skills_fit()` (stub for now — see below), computes ordinal metrics, writes mismatch file and `runs.jsonl` record. Reuses `JsonlRunLogger`, `build_run_record`, `generate_run_id` unchanged. CLI: `--gold`, `--config`, `--model`, `--provider`, `--temperature`, `--run-id`, `--workers`, `--no-mismatches`.

5. **`src/agents/skills_fit/utils.py`** — minimal `analyze_skills_fit()` that *just makes the structured LLM call*. No business logic, no thresholding, no policy. The mirror of `analyze_remote()`. Prompt is a one-paragraph stub at this point — enough to return parseable output, not enough to score well.

6. **`src/agents/skills_fit/baselines.py`** — at least one non-LLM scorer the eval has to beat. Start with a keyword-overlap baseline: tokenize the candidate profile's `core_skills` list and the job description, score 1–5 by normalized overlap count with hand-tuned thresholds. ~30 lines, no LLM calls. Wire it into `run_skills_fit_eval.py` via `--scorer {llm,keyword}` so each run records which scorer produced the numbers.

   Why this matters: without a baseline, "Spearman ρ = 0.7" looks fine in isolation but tells you nothing about whether gpt-4o-mini is earning its cost. If a 30-line keyword heuristic hits 0.65, the LLM had better do significantly better than that. The baseline number is also the floor against which Variant A (embedding evidence) should be measured later.

7. **Run the eval.** Expect terrible numbers from the stub LLM scorer (intentionally — weak prompt). The keyword baseline will probably outperform it at this stage; that's fine and informative. Commit both to `runs.jsonl` — that's the red baseline pair.

**Done criteria for Phase R:**
- `compute_ordinal_metrics` (both ordinal-agreement and top-of-list metrics) has tests and is wired into the driver
- `data/eval/skills_fit_ground_truth.jsonl` has ≥25 hand-scored records, stratified across all five bands
- `uv run scripts/run_skills_fit_eval.py --scorer llm` and `--scorer keyword` both produce `runs.jsonl` records with ordinal + top-k metrics
- At least one bad LLM run and one keyword-baseline run are in the log to anchor future improvements

### Phase G (Green) — prompt + rubric until baseline

**Branch:** `feature/skills-fit-prompt`

**Prerequisite: profile audit.** `config/profile/candidate_profile.yml` is the scoring contract — the prompt iterates against it, and an unstable profile churns the prompt. Before drafting the system prompt, finalize the profile through a dedicated audit pass: collect cross-agent input (each agent has a different evidence window, so the union catches what any single one would miss), run per-repo evidence audits where applicable (commit history is auditable; conversation memory is reconstructive), then conduct an interview-style session that pushes back on aspirational listings *and* modest understatement. Bump `profile_version` to a non-stub label and capture non-obvious choices in a sibling rationale doc for future audits.

1. **`prompts/skills_fit/system_prompt.txt`** — write the rubric. Include the calibration paragraph from "Calibration: the laundry-list problem" verbatim. Anchor each 1–5 band with what it means concretely. Lift 2–3 verbatim `_human_notes` examples from the gold set into the prompt as in-context calibration anchors.
2. **`config/agent/skills_fit.yml`** — candidate profile (skills, domains, level, preferences) + `llm:` block (provider, model, temperature). Profile content is the second knob to tune; prompt is the first.
3. **Iterate.** Re-run the eval after every prompt or profile change. Compare runs with `compare_evals.py` (will need a flag to switch metric set, or a sibling script — decide based on how messy the existing one gets).
4. **Expand the gold via teacher-batch once rubric stabilizes.** Target ≥80 records total via teacher → HITL → gold flow, confirmed/corrected via the Streamlit reviewer (see step 5). Same pattern as remote_filter — reuse the pipeline, not the code. Teacher choice compounds here in a way it doesn't in Phase R (where every record is reviewed regardless), so pick deliberately.

   **Teacher model selection.** Phase R sampled three candidates (May 2026):
   - `gpt-4o @ temp 0.1` — deterministic, capable, but softened role-type/level mismatches (scored a stretched-adjacent role 4 where 3 was defensible).
   - `gpt-5.4 @ temp 0.1` — newer capability, deterministic, comparable quality to gpt-5.5 on the sample.
   - `gpt-5.5` (temperature locked, see caveat) — strongest deceptive-2 reasoning, caught role-type/level/domain mismatches the others softened, populated `hard_concerns` correctly and independently of fit_score, cited specific JD language.

   Before kicking off the Phase G batch, run ~5 records each through the candidates, eyeball the rationales, pick the winner. Don't formalize this as an eval — review-time is the bottleneck, not metrics. Recheck the candidate list against whatever's currently frontier; this list is May 2026.

   **Caveat: reasoning models lock temperature.** GPT-5 family models (e.g., `gpt-5.5`) reject `temperature` overrides and run at their default (1.0); the API returns a 400 if you pass `--temperature 0.1`. For one-shot teacher proposals the non-determinism doesn't matter (review absorbs it). For the production scorer where rerun-reproducibility matters across many runs, prefer a model that accepts low temperatures — `gpt-5.4 @ 0.1` is currently the sweet spot for the teacher; the production scorer (`config/agent/skills_fit.yml`) should similarly stay on a temperature-honoring model.
5. **Build the skills_fit reviewer as a sibling app, not a refactor.** Copy `src/review_ui/app.py` to `src/review_ui/skills_fit_app.py` and modify in place. Do **not** refactor the existing remote-filter reviewer into a generic plugin framework — two example datasets is the minimum needed to spot the right abstraction, and one mature + one sketch will guess wrong about the variation points. Also rejected: a single-file dispatcher (`app.py -- --dataset skills_fit`); that just moves the same abstraction problem inside the file as `if/else` branches.

   `skills_fit_app.py` differs from `app.py` in these places:
   - Imports `agents.skills_fit.models` instead of `agents.remote_filter.models`
   - `STAGING = "data/staging/skills_fit_to_review.jsonl"`, `EVAL = "data/eval/skills_fit_ground_truth.jsonl"`
   - Right-column display: `score_rationale`, `fit_score` (1–5), `confidence`, `top_matches` chips, `gaps` chips, `hard_concerns` chips (red badge styling if non-empty)
   - Correction form:
     - `fit_score`: `st.radio` 1–5 — **required**
     - `confidence`: `st.radio` low/medium/high — **required**
     - `top_matches`: `st.text_area` (one per line) — **required for scores 3–5**
     - `gaps`: `st.text_area` (one per line) — **required for scores 1–4**
     - `hard_concerns`: `st.text_area` (one per line) — optional but encouraged
     - `_human_notes`: `st.text_area` — **required**, no default. The calibration artifact; the app blocks Save until it's non-empty.
     - `_correction_note`: `st.text_input` — optional, for "why I changed the model output"
   - Saved fields: `_human_fit_score`, `_human_confidence`, `_human_top_matches`, `_human_gaps`, `_human_hard_concerns`, `_human_notes` (always), `_corrected`, `_correction_note` (if applicable)
   - "Prior submission" badge shows previous `fit_score` and `confidence` instead of verdict/policy

   Run with `streamlit run src/review_ui/skills_fit_app.py`. Update `src/review_ui/README.md` to document both apps.

   **Deferred (not in this PR):**
   - Rename `app.py` → `remote_filter_app.py` for symmetry. Breaks the documented run command — park as a follow-up tidy.
   - Extract shared scaffolding (`status_dot`, `status_grid`, nav-bar, session-state init) into `src/review_ui/_shared.py`. Wait until a third reviewer exists before designing the shared layer.

6. **`src/agents/skills_fit/validation.py`** — `validate_analysis_consistency(analysis: SkillsFitAnalysis) -> list[str]`. Pydantic ensures *shape*; this catches *semantic* inconsistencies Pydantic can't. Flag-not-reject: returns a list of warning strings, the eval driver logs them to the mismatch file as diagnostic signal.

   Initial rules:
   - score 1 with ≥5 `top_matches` (suspicious — claims weak fit but lists many overlaps)
   - score 5 with non-empty `hard_concerns` (a 5 shouldn't have blockers)
   - scores 4–5 with fewer than 2 `top_matches` (under-justified)
   - scores 1–4 with empty `gaps` (under-justified)
   - `confidence=high` with vague-looking `score_rationale` (length-based heuristic, just a hint)

   The point isn't to reject imperfect output. The point is to surface suspicious patterns during prompt iteration. If the same rule keeps firing across many records, that's a prompt bug.

**Done criteria for Phase G:**
- Spearman ρ ≥ 0.7 on the gold set (placeholder target — revisit after first real numbers)
- ±1 accuracy ≥ 0.75
- `precision_at_5` ≥ 0.6 (≥3 of the predicted top 5 are actually gold ≥ 4)
- LLM scorer beats the keyword baseline on `precision_at_5` and `spearman_rho` by a material margin
- Gold set ≥ 80 records, stratified across bands and covering domain/level/credential edge cases
- Confusion 5×5 doesn't show systematic mid-band collapse (everything → 3)
- `validate_analysis_consistency` flags ≤10% of records (stable rules-fire rate means a stable prompt)
- `src/review_ui/skills_fit_app.py` functional, documented in the review_ui README

Numbers above are *targets to debate after first real data*, not contracts. Adjust once we see what the model can actually do.

### Phase B (Refactor / production) — runner, CLI, pipeline integration

**Branch:** `feature/skills-fit-runner`

Only after Phase G hits its baseline:

1. **`src/agents/skills_fit/runner.py`** — `run_skills_fit()` mirroring `remote_filter/runner.py`. Reads `data/filtered/<DATE>/remote_filter_pass.jsonl`, writes `data/scored/<DATE>/skills_fit_scored.jsonl`. Enriches each record with `_skills_fit_analysis` and `_skills_fit_metadata`.
2. **`scripts/run_skills_fit.py`** — thin entry point, same shape as `run_remote_filter.py`.
3. **CLI integration** — `uv run job-scraper skills-fit --run-date <DATE>` subcommand.
4. **`src/agents/skills_fit/README.md`** — docs for the module.
5. **Update top-level `README.md`** — mark Phase 3 as implemented; update the quick-start block.
6. **Pipeline shell snippet** in `specs/project.md` — append the `skills-fit` line to the v1 manual orchestration block.

**Done criteria for Phase B:**
- `uv run job-scraper skills-fit --run-date $(date +%F)` scores a day's filtered output end-to-end
- Output JSONL is correctly partitioned under `data/scored/<DATE>/`
- README and project.md reflect Phase 3 done
- Metadata block (`schema_version`, `prompt_hash`, **`profile_hash`**, **`profile_version`**, `commit`) is on every record. `profile_hash` is `sha256` of `config/profile/candidate_profile.yml`; `profile_version` is a human-readable date label inside the profile YAML. Without this, runs are not comparable across profile changes.

### Out-of-band: eval-driver consolidation (deferred)

After both `run_remote_filter_eval.py` and `run_skills_fit_eval.py` exist, look at what's genuinely shared (CLI scaffolding, gold loading, mismatch file writing, worker pool, run-record assembly) and what isn't (per-record evaluation function, metric set, mismatch record schema). Refactor into a shared driver only if the duplication is painful — not before. Two examples is the minimum needed to spot the right abstraction; one example is not.

---

## Out of scope for this plan

- Dispatcher / Phase 4 delivery (email, FastAPI shortlist UI)
- Local-model distillation for skills_fit (teacher-student, separate spec)
- Multi-axis sub-scores
- Full-corpus pairwise ranking (see note below)
- Fine-tuning
- CI gating on eval metrics

### Note on pairwise ranking — defer, but with a specific shape

Pairwise ranking ("is job A a better fit than job B?") is something LLMs do well, but O(n²) prohibits running it on the full daily intake. The genuinely useful version for this product is **top-bucket reranking only**:

```text
1. Score all jobs 1–5 with the skills_fit agent (this plan).
2. Take all 5s and high-confidence 4s.
3. If that set is larger than N (say, 10), run pairwise or tournament ranking on just that subset to pick the dispatched shortlist.
4. Dispatch the top N to email/UI.
```

The real product problem is rarely "is this a 4 or a 5?" — it's "I have twenty 4s, which five should I actually apply to today?" That's where pairwise earns its keep. Deferred to Phase 4 (dispatcher) work, not Phase 3.

---

## Operation: Smoosh, and what comes after

Phase R/G ships **Operation: Smoosh** — pure LLM-as-judge with `(job + profile + rubric) → JSON`. Simplest thing that could work, and the architecture every other section of this plan assumes.

The eval harness is invariant to what happens inside the agent — input is `(job, profile)`, output is `fit_score`. That means future architectural variants can be A/B'd against the same gold set without touching eval infrastructure. Recording the variants here so the future direction is explicit, not so anyone builds them in Phase R/G.

### Variant A — Hybrid: LLM scoring grounded in embedding evidence

Pre-compute structured skill-overlap evidence and inject it into the user message before scoring:

1. Extract a skill list from the job posting (LLM call or NER)
2. Embed each job-skill and each profile-skill (`text-embedding-3-small`)
3. Compute pairwise cosine similarity → structured object:
   ```json
   {
     "matched": [["C++", "C++", 0.98], ["PyTorch", "deep learning", 0.71]],
     "unmatched_job_skills": ["Kubernetes", "Go"],
     "unmatched_profile_skills": ["embedded systems"]
   }
   ```
4. Pass that evidence to the LLM alongside the job text; LLM still produces the final 1–5.

**Why it might help:** grounds the score in concrete evidence rather than vibes; catches skill-name normalization ("ML" ↔ "machine learning") that prompting alone misses; makes `score_rationale` inspectable against the evidence object.

**Why it might not:** at this volume, gpt-4o-mini reading the full posting is already decent at this. The embedding layer could add complexity without moving Spearman ρ.

**How to evaluate:** once Phase G has a baseline, run the same gold set against (a) Smoosh and (b) Smoosh + embedding evidence. If Spearman ρ moves materially, productionize. If not, kill the branch and write up the negative result.

Implementation note for whoever picks this up: at our scale, pre-compute the evidence for every job and inject into the user message — do not implement it as an agent tool call. Tool calls are for when the agent might *not* need the tool; here it always needs it.

### Variant B — Pure embedding similarity (rejected for MVP, noted for completeness)

Skip LLM scoring entirely; rank by cosine similarity between job and profile embeddings. Rejected because cosine sim captures topical overlap, not fit — a junior Python role and a principal Python architect role embed similarly, but only one matches a senior candidate. Worth revisiting only if volume grows to thousands of jobs/day and LLM cost starts to dominate.

### Other directions, parked

- **Pairwise ranking** ("is job A better than job B?") — LLMs do this very well but it's O(n²). Only viable as a reranking step on the dispatcher's top-N shortlist, never on the full daily intake.
- **Multi-axis sub-scores** (`tech_score`, `level_score`, `domain_score` summed/weighted) — already noted as YAGNI in the Schema section. Revisit if intra-band sorting becomes a real product problem.
- **Fine-tuning / distillation** — once the gold set is large enough (~200+ records), distill a local model on it. Pairs with `specs/teacher-student.md`.

---

## Open questions to resolve before Phase R starts

1. **~~Gold set seed source~~** — **Resolved.** Stratified across bands (5 per band, see Phase R step 3), not random sampling. Deceptive 2s are explicitly part of the seed.
2. **~~Candidate profile location~~** — **Resolved.** Split into `config/profile/candidate_profile.yml` with its own version label, referenced from `config/agent/skills_fit.yml`. Hashed and recorded in every scored record's metadata (`profile_hash`, `profile_version`). The profile is part of the scoring contract, not just config — runs aren't comparable across profile changes unless we track it.
3. **`compare_evals.py` extension vs. sibling script:** the existing tool assumes binary metrics columns. Cleanest is probably to add a `--metric-set {binary,ordinal}` flag and let it pick columns based on run record shape. Cheapest is a sibling `compare_skills_fit_evals.py`. Defer the decision to Phase G — by then we'll know which we want.
4. **List-field eval strategy:** `top_matches`, `gaps`, and `hard_concerns` are freeform string lists. Evaluating predicted vs gold lists requires choosing among: (a) hand-normalized set overlap (slow but rigorous), (b) embedding-similarity overlap (cheap, fuzzy), (c) spot-check only with no automated metric (pragmatic, lower signal). The Phase G semantic validator (step 6) catches *presence/absence* sanity. Decide on a content-overlap metric — if any — during Phase G mismatch review, once we see what kinds of list disagreements actually show up.
