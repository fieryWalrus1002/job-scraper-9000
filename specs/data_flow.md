# Data Flow

_Last updated: 2026-05-19_

This diagram reflects the repository's current implemented data paths. Phase 3 and Phase 4 are shown as planned downstream targets but are not yet implemented.

```mermaid
flowchart TD
    %% External sources
    subgraph sources[External Sources]
        linkedin[LinkedIn guest API]
        jobspy[JobSpy boards<br/>Indeed / ZipRecruiter / Glassdoor]
        greenhouse[Greenhouse ATS]
        lever[Lever ATS]
        ashby[Ashby ATS]
        sel[SEL Workday CXS API]
        openai[OpenAI API / Batch API]
        ollama[Ollama-compatible local endpoint]
    end

    %% Ingestion
    subgraph ingestion[Phase 1: Ingestion — complete]
        searchConfig[config/search.yml<br/>searches, boards, env expansion]
        boards[config/company_boards.json<br/>ATS discovery cache]
        failures[config/known_failures.json<br/>permanent 403/404/410 skip list]
        discover[uv run job-scraper discover]
        runConfig["uv run job-scraper run-config config/search.yml --save<br/>opt: --run-date YYYY-MM-DD<br/><br/>Each scraper internally: scrubs PII + generates dedup hash"]
        rawFlat[(data/raw/*.jsonl<br/>legacy flat Bronze)]
        rawRun[(data/raw/YYYY-MM-DD/*.jsonl<br/>run-partitioned Bronze)]
    end

    linkedin & jobspy & greenhouse & lever & ashby & sel --> runConfig
    discover --> boards --> searchConfig --> runConfig
    failures --> runConfig
    runConfig -->|no --run-date| rawFlat
    runConfig -->|--run-date| rawRun

    %% Prefilter
    subgraph prefilter[Phase 1.5: Prefilter Router — complete]
        pfConfig[config/agent/prefilter.yml<br/>country gate + local allowlist]
        pfCli["uv run job-scraper prefilter<br/>opt: --run-date YYYY-MM-DD<br/><br/>Resolves output paths before routing"]
        pfRouter[src/prefilter<br/>deterministic routing rules]
        pfRemote[(data/prefiltered/YYYY-MM-DD/<br/>remote_filter_input.jsonl)]
        pfLocal[(data/local/YYYY-MM-DD/<br/>local_jobs.jsonl)]
        pfTrash[(data/trash/YYYY-MM-DD/<br/>prefilter_trash.jsonl)]
    end

    rawFlat & rawRun --> pfCli
    pfConfig --> pfCli --> pfRouter
    pfRouter -->|remote_filter_candidate| pfRemote
    pfRouter -->|local_candidate| pfLocal
    pfRouter -->|reject| pfTrash

    %% Teacher / HITL gold creation
    subgraph gold[Teacher + HITL gold dataset — implemented, dataset expanding]
        teacherPrompt[prompts/remote_agent_teacher/system_prompt.txt]
        prepare[uv run python scripts/prepare_batch.py]
        teacherJobs[(data/batch/YYYY-MM-DD/<br/>gpt_teacher_jobs.jsonl)]
        teacherReq[(data/batch/YYYY-MM-DD/<br/>gpt_teacher_batch.jsonl)]
        submitTeacher[uv run python scripts/submit_batch.py<br/>upload / poll / download]
        teacherResults[(data/batch/YYYY-MM-DD/<br/>gpt_teacher_results.jsonl)]
        merge[uv run python scripts/merge_batch_results.py]
        staging[(data/staging/to_review.jsonl<br/>Silver — teacher-annotated)]
        sample[uv run python scripts/sample_for_review.py]
        reviewBatch[(data/staging/review_batch.jsonl)]
        review[streamlit run src/review_ui/app.py<br/>confirm / correct / skip]
        goldData[(data/eval/ground_truth.jsonl<br/>Gold — human-verified labels)]
    end

    rawFlat & rawRun --> prepare
    teacherPrompt --> prepare
    prepare --> teacherJobs & teacherReq
    teacherReq --> submitTeacher
    openai --> submitTeacher --> teacherResults
    teacherJobs & teacherResults --> merge --> staging
    rawFlat & rawRun -. optional sampling .-> sample --> reviewBatch
    staging & reviewBatch --> review --> goldData

    %% Runtime remote filter
    subgraph remote[Phase 2: Remote Filter — complete]
        rfConfig[config/agent/remote_agent.yml<br/>provider, model, policy thresholds]
        rfPrompt[prompts/remote_agent/system_prompt.txt]
        rfCli["uv run job-scraper remote-filter<br/>opt: --run-date YYYY-MM-DD"]
        rfAgent[src/agents/remote_filter<br/>RemoteAnalysis structured output]
        rfPass[(data/filtered/YYYY-MM-DD/<br/>remote_filter_pass.jsonl)]
        rfTrash[(data/trash/YYYY-MM-DD/<br/>remote_filter_trash.jsonl)]
    end

    pfRemote --> rfCli
    rfConfig & rfPrompt --> rfCli
    openai & ollama --> rfAgent
    rfCli --> rfAgent
    rfAgent -->|PASS| rfPass
    rfAgent -->|TRASH| rfTrash

    %% Eval path
    subgraph eval[Remote filter eval + regression tracking — complete]
        evalRun[uv run scripts/run_remote_filter_eval.py<br/>--workers N]
        evalSubmit[uv run python scripts/submit_eval_batch.py]
        evalSidecar[(data/eval/eval_batch_RUN_ID.json<br/>sidecar metadata)]
        evalRequests[(data/eval/batch/eval_requests_RUN_ID.jsonl)]
        evalPoll[uv run python scripts/poll_eval_batch.py]
        evalResults[(data/eval/batch/eval_results_RUN_ID.jsonl)]
        mismatches[(data/eval/mismatches_RUN_ID.jsonl)]
        runs[(data/eval/runs.jsonl<br/>metrics + provenance)]
        compare[uv run scripts/compare_evals.py]
    end

    goldData --> evalRun & evalSubmit
    rfConfig & rfPrompt --> evalRun
    openai --> evalSubmit
    evalRun --> mismatches & runs
    evalSubmit --> evalRequests & evalSidecar
    evalSidecar --> evalPoll
    evalPoll --> evalResults & mismatches & runs
    runs --> compare

    %% Planned downstream
    subgraph future[Planned downstream — not yet implemented]
        skillsConfig[config/agent/skills_fit.yml]
        skillsPrompt[prompts/skills_fit/system_prompt.txt]
        skillsFit[Phase 3: Skills Fit Agent<br/>scores remote + local jobs against candidate profile]
        scored[(data/scored/YYYY-MM-DD/<br/>skills_fit_scored.jsonl)]
        dispatch[Phase 4: Dispatch<br/>email or FastAPI web GUI]
    end

    rfPass -. planned .-> skillsFit
    pfLocal -. planned .-> skillsFit
    skillsConfig & skillsPrompt -. planned .-> skillsFit
    skillsFit -. planned .-> scored -. planned .-> dispatch

    %% Styling
    classDef complete fill:#e8f5e9,stroke:#2e7d32,color:#111;
    classDef data fill:#e3f2fd,stroke:#1565c0,color:#111;
    classDef future fill:#f3e5f5,stroke:#7b1fa2,stroke-dasharray: 5 5,color:#111;
    classDef external fill:#eeeeee,stroke:#616161,color:#111;

    class linkedin,jobspy,greenhouse,lever,ashby,sel,openai,ollama external;
    class runConfig,discover,pfCli,pfRouter,prepare,submitTeacher,merge,sample,review,rfCli,rfAgent,evalRun,evalSubmit,evalPoll,compare complete;
    class rawFlat,rawRun,pfRemote,pfLocal,pfTrash,teacherJobs,teacherReq,teacherResults,staging,reviewBatch,goldData,rfPass,rfTrash,evalSidecar,evalRequests,evalResults,mismatches,runs,scored data;
    class skillsConfig,skillsPrompt,skillsFit,dispatch future;
```

## Notes

- PII scrubbing and deduplication (SHA-256 of company + title + location) happen inside each scraper's `.scrape()` call — they are not separate pipeline stages.
- `--run-date YYYY-MM-DD` is optional on `run-config`, `prefilter`, and `remote-filter`. When provided, each stage reads/writes under a dated subdirectory. Without it, the legacy flat layout is used. Either way, explicit `--input`/`--output` flags override everything.
- The teacher/HITL path (`prepare_batch` → `submit_batch` → `merge_batch_results` → Streamlit review) is separate from the eval path (`submit_eval_batch` / `poll_eval_batch`). The teacher path builds the gold dataset; the eval path measures model performance against it.
- Phase 3 (Skills Fit) will consume both remote-filter pass records **and** local-candidate jobs from the prefilter — both are worth scoring against the candidate profile.
- Phase 4 (Dispatch) delivers the ranked shortlist from `data/scored/` via email or FastAPI web UI.
