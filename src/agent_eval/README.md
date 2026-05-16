# agent_eval

The agent eval pipeline for job-scraper-9000. We aim for an extensible, professional-grade evaluation pipeline that meets with LLMOps standards.

Working from the spec [[../../specs/eval_framework_requirements.md]]

Dataset design goals are in [[../../specs/remote_filter_golden_dataset_requirements.md]] We have an imbalanced golden set now [[../../data/eval/ground_truth.jsonl]], but we'll fix that soon. Not in scope for the code, though.

Files:

``` bash
src/agent_eval/
├── __init__.py                     # exports RunLogger, JsonlRunLogger
├── logger.py                       # RunLogger Protocol + JsonlRunLogger
├── provenance.py                   # build_run_record() — git, env, hashes
└── metrics.py                      # compute_metrics(tp, fp, tn, fn) → dict

scripts/
├── run_remote_filter_eval.py       # remote_filter driver — imports both
└── compare_evals.py                # reads runs.jsonl, prints table. Should we have one for each agent type? 
```

**Notice**: src/utils/git_info.py already exists — provenance.py should call it rather than re-implement git state capture.

Agent-specific code for eval should reside in their own src/agents/* subfolder. This module is for the generic code that we will use for many agent types: `remote_filter`, `skills_fit`, 