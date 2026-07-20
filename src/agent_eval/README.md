# agent_eval

Reusable evaluation infrastructure for job-scraper-9000 agents.

This package is intentionally agent-agnostic: it handles run logging, provenance, environment capture, hashing, and metric calculation. Agent-specific eval drivers live outside this package — currently `scripts/run_remote_filter_eval.py` for the remote-filter agent and `scripts/run_skills_fit_eval.py` for the skills-fit agent.

Working from the spec: [`../../specs/eval_framework_requirements.md`](../../specs/eval_framework_requirements.md). The original remote-filter batch-eval path was retired after the eval moved to classifier-native categorical metrics.

______________________________________________________________________

## What it provides

```text
src/agent_eval/
├── __init__.py        # exports provenance helpers
├── provenance.py      # run IDs, hashes, git/env metadata, run-record assembly
└── metrics.py         # compute_categorical_metrics() — labeled categorical confusion
                       # compute_metrics() — generic legacy binary metrics
                       # compute_ordinal_metrics() — skills-fit ordinal + top-k metrics
```

Run logging (`RunLogger`, `JsonlRunLogger`, `MLFlowRunLogger`) lives in `utils.run_logger`.

The package is used by:

```text
scripts/run_remote_filter_eval.py   # remote-filter categorical eval, supports --workers
scripts/compare_evals.py            # reads data/eval/runs.jsonl
scripts/run_skills_fit_eval.py      # skills-fit eval driver (--scorer {llm,keyword})
```

______________________________________________________________________

## Data artifacts

Eval data lives under `data/eval/`:

| Path                                      | Purpose                                                                     |
| ----------------------------------------- | --------------------------------------------------------------------------- |
| `data/eval/ground_truth.jsonl`            | Remote-filter human-verified gold from the HITL review UI                   |
| `data/eval/skills_fit_ground_truth.jsonl` | Skills-fit human-verified gold from the teacher-first markdown / CLI review |
| `data/eval/runs.jsonl`                    | Append-only eval run history (both agents)                                  |
| `data/eval/mismatches_<run_id>.jsonl`     | Per-run mismatch records                                                    |

`data/**/*.jsonl` is gitignored so local eval artifacts are not committed.

______________________________________________________________________

## Run-record provenance

Each eval run records:

- run ID and timestamp
- git commit + dirty flag
- gold file path + hash
- resolved prompt hash
- provider/model/temperature config
- Python/platform/uv/lockfile metadata
- categorical confusion matrix, per-class precision/recall/F1, macro/micro metrics, and travel MAE (remote-filter)
- ordinal metrics (exact / off-by-one / MAE / bias / Spearman) + top-k metrics + 5x5 confusion (skills-fit)
- scorer choice (`llm` vs `keyword`) and profile metadata (`profile_hash`, `profile_version`) for skills-fit runs
- mismatch artifact path

This makes prompt, model, profile, config, and dataset changes comparable across runs.

______________________________________________________________________

## Current baseline

Remote-filter eval now reports classifier-native 4-way categorical metrics (`remote`, `hybrid`, `onsite`, `unclear`) plus travel-days MAE. Use `scripts/compare_evals.py --last 5` to inspect recent local runs.

______________________________________________________________________

## Design note

Generic eval utilities belong in `src/agent_eval/`. Generic run logging (`RunLogger`, `JsonlRunLogger`, `MLFlowRunLogger`) belongs in `utils.run_logger`. Agent-specific schemas, prompts, and scoring logic should live with their agent package under `src/agents/*` or in that agent's eval driver script.
