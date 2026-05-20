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
```

---

## Phase R — running the eval

The harness is ready. The seed gold set is not (it's a manual task).

**1. Sample candidate records for hand-scoring:**

```bash
uv run scripts/prepare_skills_fit_seed.py --n 40 --in data/filtered/
```

Writes `data/staging/skills_fit_seed_template.jsonl` with empty `_human_*` fields.

**2. Hand-score 25 records, stratified 5×5 across bands.**

Open the template, score each record. Aim for:

| Count | Type |
| --- | --- |
| 5 | obvious 5s |
| 5 | obvious 4s |
| 5 | ambiguous 3s |
| 5 | **deceptive 2s** — mention your stack but mismatch on level/credential/domain/role type |
| 5 | hard-reject 1s |

`_human_notes` is **mandatory**, not optional — those notes become the in-context calibration examples in Phase G. See the Calibration section of the spec.

Save scored records (drop unused candidates) to `data/eval/skills_fit_ground_truth.jsonl`.

**3. Run the eval with both scorers:**

```bash
uv run scripts/run_skills_fit_eval.py --scorer keyword --run-id phase_r_baseline
uv run scripts/run_skills_fit_eval.py --scorer llm --run-id phase_r_stub
```

Expected outcome: terrible LLM numbers (intentionally — the prompt is a stub). The keyword baseline will probably outperform it. That's the red baseline pair anchoring Phase G.

Run records land in `data/eval/runs.jsonl` with full provenance: prompt hash, profile hash, profile version, git commit, scorer choice, and the full metric set (ordinal + top-k).
