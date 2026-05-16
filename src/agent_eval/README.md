# agent_eval

Reusable evaluation infrastructure for job-scraper-9000 agents.

This package is intentionally agent-agnostic: it handles run logging, provenance, environment capture, hashing, and metric calculation. Agent-specific eval drivers live outside this package, currently in `scripts/run_remote_filter_eval.py` for the remote-filter agent.

Working from the spec: [`../../specs/eval_framework_requirements.md`](../../specs/eval_framework_requirements.md). Implementation status: SC-1 through SC-7 complete.

---

## What it provides

```text
src/agent_eval/
├── __init__.py        # exports RunLogger, JsonlRunLogger, provenance helpers
├── logger.py          # RunLogger Protocol, JsonlRunLogger, MLFlowRunLogger stub
├── provenance.py      # run IDs, hashes, git/env metadata, run-record assembly
└── metrics.py         # compute_metrics(tp, fp, tn, fn, skipped)
```

The package is used by:

```text
scripts/run_remote_filter_eval.py   # synchronous eval, supports --workers
scripts/submit_eval_batch.py        # OpenAI Batch API eval submission
scripts/poll_eval_batch.py          # batch result scoring + run logging
scripts/compare_evals.py            # reads data/eval/runs.jsonl
```

---

## Data artifacts

Eval data lives under `data/eval/`:

| Path | Purpose |
| --- | --- |
| `data/eval/ground_truth.jsonl` | Human-verified gold dataset from the HITL review UI |
| `data/eval/runs.jsonl` | Append-only eval run history |
| `data/eval/mismatches_<run_id>.jsonl` | Per-run mismatch records |
| `data/eval/batch/` | OpenAI Batch API request/result files |
| `data/eval/eval_batch_<run_id>.json` | Batch eval sidecar metadata |

`data/**/*.jsonl` is gitignored so local eval artifacts are not committed.

---

## Run-record provenance

Each eval run records:

- run ID and timestamp
- git commit + dirty flag
- gold file path + hash
- resolved prompt hash
- provider/model/temperature
- policy thresholds
- Python/platform/uv/lockfile metadata
- confusion matrix + accuracy/precision/recall/F1
- mismatch artifact path

This makes prompt, model, config, and dataset changes comparable across runs.

---

## Current baseline

Latest smoke test on the 104-record remote-filter gold dataset:

```text
run_id:      smoke_parallel_20260516_045209_a6da
command:     uv run scripts/run_remote_filter_eval.py --workers 4 --run-id smoke_parallel
model:       gpt-4o-mini
temperature: 0.1
records:     104 evaluated, 0 skipped
TP/FP/TN/FN: 29 / 12 / 61 / 2
accuracy:    0.8654
precision:   0.7073
recall:      0.9355
f1:          0.8056
```

Primary tuning target: reduce false positives where onsite or location-restricted jobs are predicted as pass.

---

## Design note

Generic eval utilities belong in `src/agent_eval/`. Agent-specific schemas, prompts, and scoring logic should live with their agent package under `src/agents/*` or in that agent's eval driver script.
