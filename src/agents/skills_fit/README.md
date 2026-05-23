# skills_fit agent

Phase 3 of the pipeline — scores remote-filtered jobs against the candidate profile on a 1–5 ordinal scale.

**Status:** Phase R (red baseline) closed. Schema, eval harness (ordinal + top-k metrics), keyword baseline, calibrated rubric prompt, the v5 candidate profile (LLM-reframe), and a 21-record human-ratified seed gold set are committed. The pinned Phase R champion is recorded in [`config/eval/champions.yml`](../../../config/eval/champions.yml). Phase G (calibration loop, one-lever-per-PR) is the active phase; the workflow below documents how the seed gold set was built and can be re-used when expanding to ≥80 records.

See [specs/skills_fit_agent_plan.md](../../../specs/skills_fit_agent_plan.md) for the full plan, including the eval-forward sequencing (Phase R → G → B), the calibration discipline, and the architectural variants parked for later.

---

## Layout

```text
src/agents/skills_fit/
├── __init__.py
├── models.py         # SkillsFitAnalysis Pydantic schema (fit_score, confidence,
│                     #   score_rationale, top_matches, gaps, hard_concerns)
├── utils.py          # analyze_skills_fit() — structured LLM call;
│                     #   _format_profile_block() reads education as a top-level field
└── baselines.py      # keyword_overlap_analyze() — non-LLM baseline

prompts/skills_fit/
└── system_prompt.txt # Real rubric: calibration paragraph, skill-role classification
                     #   table, band definitions, field-by-field instructions

config/agent/skills_fit.yml          # LLM + profile pointer + score_bands
config/profile/candidate_profile.yml # The scoring contract — versioned (profile_version)
                                     # and hashed (profile_hash) in every run record.
                                     # Current: v5 (2026-05-22, LLM-reframe).
                                     # Auto-snapshotted to config/profile/old_profiles/
                                     # on every eval run (gitignored, contains PII).

scripts/prepare_skills_fit_seed.py        # sampler — blank template for hand-scoring
scripts/propose_skills_fit_seed.py        # teacher LLM proposes labels (HITL path)
scripts/render_skills_fit_review_md.py    # render proposals as per-record markdown
scripts/parse_skills_fit_review_md.py     # parse reviewed markdown back to gold JSONL
scripts/score_skills_fit_seed.py          # CLI scorer alternative — teacher-aware
scripts/run_skills_fit_eval.py            # eval driver — --scorer {llm,keyword}
```

---

## Phase R — running the eval

The harness is ready. The seed gold set is a manual task. The recommended path is teacher-first HITL via markdown review; a CLI alternative exists for headless work.

**1. Sample candidate records:**

```bash
uv run scripts/prepare_skills_fit_seed.py --n 40 --in data/filtered/
```

Writes `data/staging/skills_fit_seed_template.jsonl` with empty `_human_*` fields.

**2. Run teacher proposals.** Cold single-rater labeling drifts in calibration across 25+ records, and a literal-reading reviewer additionally over-rejects due to JD aspirational phrasing ("required" / "preferred" / "experience with"). Teacher-first mitigates both. See the "Teacher-first HITL alternative" subsection in the spec.

```bash
uv run scripts/propose_skills_fit_seed.py --model gpt-5.5 --temperature 1.0
```

Writes `data/staging/skills_fit_seed_proposed.jsonl` with `_teacher_*` fields populated. Resume-safe by `source_job_id`. The proposer calls `load_dotenv()`, so `OPENAI_API_KEY` from `.env` is picked up automatically.

`gpt-5.5` rejects custom temperatures and runs at its default (1.0); pass `--temperature 1.0` for clarity, or use `gpt-5.4` / `gpt-4o` if rerun-reproducibility at lower temperatures matters.

**3a. Markdown review (recommended).** Render one markdown file per posting with teacher labels visible, ratify or override in the markdown, then parse back to gold JSONL.

```bash
uv run scripts/render_skills_fit_review_md.py
# review files appear under data/staging/skills_fit_review/
uv run scripts/parse_skills_fit_review_md.py
```

**3b. Headless CLI alternative.** For terminal-only review:

```bash
uv run scripts/score_skills_fit_seed.py
```

The CLI auto-detects the proposed file. When present: shows the teacher's labels next to each posting, prompts `a` accept / `1-5` override / `s` skip / `q` quit, with press-enter-to-keep defaults for the list fields. When absent: scores from blank.

Both paths write to the same gold file: `data/eval/skills_fit_ground_truth.jsonl`. Teacher fields are preserved alongside human labels for audit trail.

**Target stratification — 25 records, 5 per band:**

| Count | Type |
| --- | --- |
| 5 | obvious 5s |
| 5 | obvious 4s |
| 5 | ambiguous 3s |
| 5 | **deceptive 2s** — mention your stack but mismatch on level/credential/domain/role type |
| 5 | hard-reject 1s |

`_human_notes` is **mandatory**, not optional — those notes become the in-context calibration examples in Phase G, and are especially load-bearing on flips (where you disagreed with the teacher). See the Calibration section of the spec.

**4. Run the eval with both scorers:**

```bash
uv run scripts/run_skills_fit_eval.py --scorer keyword --run-id phase_r_keyword
uv run scripts/run_skills_fit_eval.py --scorer llm     --run-id phase_r_llm_rubric
```

The Phase R prompt is now the real rubric (calibration paragraph + skill-role classification + band definitions), not the original one-paragraph stub. The "intentionally weak LLM vs. keyword baseline" framing from the original Phase R plan no longer holds — both scorers are now legitimate measurements, and the keyword baseline anchors the floor while the LLM scorer is what Phase G will iterate on. Run records land in `data/eval/runs.jsonl` with full provenance: prompt hash, profile hash, `profile_version`, git commit, scorer choice, and the full metric set (ordinal + top-k).
