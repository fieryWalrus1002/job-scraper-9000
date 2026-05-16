# Data Flow

_Last updated: 2026-05-16_

This diagram reflects the implemented data paths as of today. Phase 3 and Phase 4 are shown as future/downstream targets, but they are not implemented yet.

```mermaid
flowchart TD
    %% External sources
    subgraph sources[Job Sources]
        linkedin[LinkedIn guest API]
        jobspy[JobSpy boards<br/>Indeed / ZipRecruiter / Glassdoor]
        greenhouse[Greenhouse ATS]
        lever[Lever ATS]
        ashby[Ashby ATS]
    end

    %% Ingestion
    subgraph ingestion[Phase 1: Ingestion - complete]
        config[config/search.yml<br/>search + source config]
        cli[uv run job-scraper run-config ... --save]
        discover[job-scraper discover<br/>company ATS discovery]
        skiplist[permanent failure skip list<br/>403 / 404 / 410]
        scrub[PII scrubber]
        dedupe[Deduplicate<br/>SHA-256 company + title + location]
        raw[(data/raw/*.jsonl<br/>Bronze scraped jobs)]
    end

    linkedin --> cli
    jobspy --> cli
    greenhouse --> cli
    lever --> cli
    ashby --> cli
    config --> cli
    discover --> config
    skiplist --> cli
    cli --> scrub --> dedupe --> raw

    %% Prefilter router
    subgraph prefilter[Phase 1.5: Prefilter Router - complete]
        pfCli[uv run job-scraper prefilter<br/>or scripts/run_prefilter.py]
        pfConfig[config/agent/prefilter.yml<br/>country gate + local allowlist]
        pfRouter[src/prefilter<br/>deterministic routing rules]
        pfRemote[(data/prefiltered/remote_filter_input.jsonl)]
        pfLocal[(data/local/local_jobs.jsonl)]
        pfTrash[(data/trash/prefilter_trash.jsonl)]
    end

    raw --> pfCli
    pfConfig --> pfCli
    pfCli --> pfRouter
    pfRouter -->|REMOTE_FILTER_CANDIDATE| pfRemote
    pfRouter -->|LOCAL_CANDIDATE| pfLocal
    pfRouter -->|REJECT| pfTrash

    %% Teacher / HITL gold creation
    subgraph gold[Teacher + HITL gold dataset path - complete, dataset still being expanded]
        prepare[python scripts/prepare_batch.py]
        teacherReq[(data/raw/gpt_teacher_batch.jsonl<br/>OpenAI Batch request)]
        openaiTeacher[OpenAI teacher model<br/>batch API]
        teacherResults[(data/raw/gpt_teacher_results.jsonl<br/>downloaded batch results)]
        merge[python scripts/merge_batch_results.py]
        staging[(data/staging/to_review.jsonl<br/>Silver teacher-annotated jobs)]
        review[Streamlit HITL review UI<br/>src/review_ui/app.py]
        goldData[(data/eval/ground_truth.jsonl<br/>Gold human-verified labels)]
        sample[python scripts/sample_for_review.py<br/>optional spot-check path]
        reviewBatch[(data/staging/review_batch.jsonl)]
    end

    raw --> prepare --> teacherReq --> openaiTeacher --> teacherResults --> merge
    raw --> merge --> staging --> review --> goldData
    raw -. optional sampling .-> sample --> reviewBatch --> review

    %% Runtime remote filter
    subgraph remote[Phase 2: Remote Filter runtime - core complete]
        rfCli[uv run job-scraper remote-filter<br/>or scripts/run_remote_filter.py]
        rfConfig[config/agent/remote_agent.yml<br/>policy thresholds + LLM config]
        rfPrompt[prompts/remote_agent/system_prompt.txt]
        rfAgent[src/agents/remote_filter<br/>structured RemoteAnalysis]
        passOut[(data/filtered/remote_filter_pass.jsonl)]
        trashOut[(data/trash/remote_filter_trash.jsonl)]
    end

    pfRemote --> rfCli
    raw -. legacy/manual input .-> rfCli
    rfConfig --> rfCli
    rfPrompt --> rfCli
    rfCli --> rfAgent
    rfAgent -->|PASS| passOut
    rfAgent -->|TRASH| trashOut

    %% Eval path
    subgraph eval[Remote Filter eval + regression tracking - complete]
        evalRun[uv run scripts/run_remote_filter_eval.py<br/>--workers N]
        batchSubmit[uv run python scripts/submit_eval_batch.py]
        batchPoll[uv run python scripts/poll_eval_batch.py]
        batchSidecar[(data/eval/eval_batch_*.json<br/>sidecar metadata)]
        batchRaw[(data/eval/batch/*<br/>downloaded batch outputs)]
        mismatches[(data/eval/mismatches_*.jsonl)]
        runs[(data/eval/runs.jsonl<br/>metrics + provenance)]
        compare[uv run scripts/compare_evals.py]
    end

    goldData --> evalRun
    rfConfig --> evalRun
    rfPrompt --> evalRun
    evalRun --> mismatches
    evalRun --> runs

    goldData --> batchSubmit --> batchSidecar --> batchPoll
    batchPoll --> batchRaw
    batchPoll --> mismatches
    batchPoll --> runs
    runs --> compare

    %% Future downstream phases
    subgraph future[Planned downstream paths - not implemented yet]
        skillsFit[Phase 3 Skills Fit Agent<br/>planned]
        scored[(data/scored/skills_fit_scored.jsonl<br/>planned)]
        dispatch[Phase 4 Dispatch<br/>email or FastAPI GUI planned]
    end

    passOut -. planned input .-> skillsFit -. planned output .-> scored -. planned .-> dispatch

    %% Styling
    classDef complete fill:#e8f5e9,stroke:#2e7d32,color:#111;
    classDef active fill:#fff8e1,stroke:#f9a825,color:#111;
    classDef data fill:#e3f2fd,stroke:#1565c0,color:#111;
    classDef future fill:#f3e5f5,stroke:#7b1fa2,stroke-dasharray: 5 5,color:#111;

    class ingestion,prefilter,gold,remote,eval complete;
    class raw,pfRemote,pfLocal,pfTrash,teacherReq,teacherResults,staging,goldData,reviewBatch,passOut,trashOut,batchSidecar,batchRaw,mismatches,runs,scored data;
    class future,skillsFit,dispatch future;
```

## Notes

- `data/raw/*.jsonl` is the immutable scrape source truth.
- The prefilter router now splits raw data into a remote-filter candidate bucket, a local bucket, and a prefilter trash bucket.
- Remote-filter production output currently splits records into `data/filtered/remote_filter_pass.jsonl` and `data/trash/remote_filter_trash.jsonl`.
- Eval does **not** read production pass/trash outputs; it reads `data/eval/ground_truth.jsonl`, reruns the agent, and appends metrics/provenance to `data/eval/runs.jsonl`.
- The next planned data path is Phase 3: `data/filtered/remote_filter_pass.jsonl` → Skills Fit Agent → `data/scored/skills_fit_scored.jsonl`.
