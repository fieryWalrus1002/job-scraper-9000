# skills_fit agent

Phase 3 of the pipeline — scores remote-filtered jobs against the candidate profile on a 1–5 ordinal scale.

**Status:** Phase R (red baseline). Schema, eval harness, and intentionally weak LLM scorer + keyword baseline are in place. Full prompt, calibrated rubric, and gold-set expansion happen in Phase G.

See [specs/skills_fit_agent_plan.md](../../../specs/skills_fit_agent_plan.md) for the full plan, including the eval-forward sequencing (Phase R → G → B), the calibration discipline, and the architectural variants parked for later.

---

## Layout

```text
src/agents/skills_fit/
├── __init__.py
├── models.py         # SkillsFitAnalysis Pydantic schema
├── utils.py          # analyze_skills_fit() — structured LLM call
└── baselines.py      # keyword_overlap_analyze() — non-LLM baseline

prompts/skills_fit/
└── system_prompt.txt # Phase R stub — intentionally weak

config/agent/skills_fit.yml          # LLM + profile pointer
config/profile/candidate_profile.yml # the scoring contract (versioned, hashed in metadata)

scripts/run_skills_fit_eval.py       # eval driver, both scorers
scripts/prepare_skills_fit_seed.py   # sampler to make hand-scoring easier
scripts/propose_skills_fit_seed.py   # teacher LLM proposes labels (HITL path)
scripts/score_skills_fit_seed.py     # CLI scorer — teacher-aware when proposals exist
```

---

## Phase R — running the eval

The harness is ready. The seed gold set is a manual task. Two paths are supported; the spec's Phase R step 3 describes when to pick which.

**1. Sample candidate records:**

```bash
uv run scripts/prepare_skills_fit_seed.py --n 40 --in data/filtered/
```

Writes `data/staging/skills_fit_seed_template.jsonl` with empty `_human_*` fields.

**2a. (Optional but recommended) Run teacher proposals.** Cold single-rater labeling drifts in calibration across 25+ records, and a literal-reading reviewer additionally over-rejects due to JD aspirational phrasing ("required" / "preferred" / "experience with"). Teacher-first mitigates both. See the "Teacher-first HITL alternative" subsection in the spec.

```bash
uv run scripts/propose_skills_fit_seed.py --model gpt-4o
```

Writes `data/staging/skills_fit_seed_proposed.jsonl` with `_teacher_*` fields populated. Resume-safe by `source_job_id`.

**2b. Score 25 records, stratified 5×5 across bands.**

```bash
uv run scripts/score_skills_fit_seed.py
```

The CLI auto-detects the proposed file. When present: shows the teacher's labels next to each posting, prompts `a` accept / `1-5` override / `s` skip / `q` quit, with press-enter-to-keep defaults for the list fields. When absent: scores from blank.

Aim for:

| Count | Type |
| --- | --- |
| 5 | obvious 5s |
| 5 | obvious 4s |
| 5 | ambiguous 3s |
| 5 | **deceptive 2s** — mention your stack but mismatch on level/credential/domain/role type |
| 5 | hard-reject 1s |

`_human_notes` is **mandatory**, not optional — those notes become the in-context calibration examples in Phase G, and are especially load-bearing on flips (where you disagreed with the teacher). See the Calibration section of the spec.

Scored records append to `data/eval/skills_fit_ground_truth.jsonl`. Teacher fields are preserved alongside human labels for audit trail.

**3. Run the eval with both scorers:**

```bash
uv run scripts/run_skills_fit_eval.py --scorer keyword --run-id phase_r_baseline
uv run scripts/run_skills_fit_eval.py --scorer llm --run-id phase_r_stub
```

Expected outcome: terrible LLM numbers (intentionally — the prompt is a stub). The keyword baseline will probably outperform it. That's the red baseline pair anchoring Phase G.

Run records land in `data/eval/runs.jsonl` with full provenance: prompt hash, profile hash, profile version, git commit, scorer choice, and the full metric set (ordinal + top-k).
