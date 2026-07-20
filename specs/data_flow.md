# Data Flow

_Last updated: 2026-05-21_

This diagram reflects the repository's current implemented data paths. Phase 3 (Skills Fit) is partially implemented: the ordinal eval harness, real rubric prompt, keyword baseline, v4 candidate profile, and teacher-first HITL seed-gold workflow are landed; the production runner and `job-scraper skills-fit` CLI subcommand land in Phase B (see [skills_fit_agent_plan.md](skills_fit_agent_plan.md)). Phase 4 (Dispatch) remains planned.

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

    %% HITL gold creation from production classifier proposals
    subgraph gold[Remote-filter HITL gold dataset — implemented, dataset expanding]
        sample[uv run scripts/sample_for_review.py]
        staging[(data/staging/to_review.jsonl<br/>Silver — classifier proposals)]
        review[streamlit run src/review_ui/app.py<br/>confirm / correct / skip]
        goldData[(data/eval/ground_truth.jsonl<br/>Gold — human-verified labels)]
    end

    %% Runtime remote filter
    subgraph remote[Phase 2: Remote Filter — complete]
        rfConfig[config/agent/remote_agent.yml<br/>provider, model]
        rfPrompt[prompts/remote_agent/system_prompt.txt]
        rfCli["uv run job-scraper remote-filter<br/>opt: --run-date YYYY-MM-DD"]
        rfAgent[src/agents/remote_filter<br/>RemoteAnalysis structured output]
        rfClassified[(data/filtered/YYYY-MM-DD/<br/>remote_filter_classified.jsonl)]
    end

    pfRemote --> rfCli
    rfConfig & rfPrompt --> rfCli
    openai & ollama --> rfAgent
    rfCli --> rfAgent
    rfAgent -->|classified| rfClassified
    rfClassified --> sample --> staging --> review --> goldData

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

    %% Skills fit — eval harness landed, production runner deferred to Phase B
    subgraph skills[Phase 3: Skills Fit — eval harness complete; production runner in Phase B]
        skillsConfig[config/agent/skills_fit.yml<br/>llm + profile pointer + score_bands]
        skillsProfile[config/profile/candidate_profile.yml<br/>versioned profile_version, hashed in metadata]
        skillsPrompt[prompts/skills_fit/system_prompt.txt<br/>real rubric + calibration paragraph]
        sfPrepare[uv run scripts/prepare_skills_fit_seed.py]
        sfTemplate[(data/staging/skills_fit_seed_template.jsonl)]
        sfPropose[uv run scripts/propose_skills_fit_seed.py<br/>teacher LLM proposes labels]
        sfProposed[(data/staging/skills_fit_seed_proposed.jsonl<br/>_teacher_* fields)]
        sfRender[uv run scripts/render_skills_fit_review_md.py]
        sfReviewMd[(data/staging/skills_fit_review/*.md<br/>per-record human review)]
        sfParse[uv run scripts/parse_skills_fit_review_md.py]
        sfScoreCli[uv run scripts/score_skills_fit_seed.py<br/>headless CLI alternative]
        sfGold[(data/eval/skills_fit_ground_truth.jsonl<br/>Gold — _teacher_* + _human_* fields)]
        sfEval[uv run scripts/run_skills_fit_eval.py<br/>--scorer {llm,keyword}]
        sfRuns[(data/eval/runs.jsonl<br/>+ prompt_hash, profile_hash, profile_version)]
        sfRunner[Phase B: Skills Fit runner<br/>uv run job-scraper skills-fit --run-date]
        scored[(data/scored/YYYY-MM-DD/<br/>skills_fit_scored.jsonl)]
    end

    subgraph future[Planned downstream — not yet implemented]
        dispatch[Phase 4: Dispatch<br/>email or FastAPI web GUI]
    end

    rfClassified --> sfPrepare --> sfTemplate
    sfTemplate --> sfPropose
    skillsConfig & skillsProfile & skillsPrompt --> sfPropose
    openai --> sfPropose --> sfProposed
    sfProposed --> sfRender --> sfReviewMd --> sfParse --> sfGold
    sfProposed -. headless alt .-> sfScoreCli --> sfGold
    sfGold --> sfEval
    skillsConfig & skillsProfile & skillsPrompt --> sfEval
    openai & ollama --> sfEval
    sfEval --> sfRuns
    rfClassified -. Phase B .-> sfRunner
    pfLocal -. Phase B .-> sfRunner
    skillsConfig & skillsProfile & skillsPrompt -. Phase B .-> sfRunner
    sfRunner -. Phase B .-> scored -. planned .-> dispatch

    %% Styling
    classDef complete fill:#e8f5e9,stroke:#2e7d32,color:#111;
    classDef data fill:#e3f2fd,stroke:#1565c0,color:#111;
    classDef future fill:#f3e5f5,stroke:#7b1fa2,stroke-dasharray: 5 5,color:#111;
    classDef external fill:#eeeeee,stroke:#616161,color:#111;

    class linkedin,jobspy,greenhouse,lever,ashby,sel,openai,ollama external;
    class runConfig,discover,pfCli,pfRouter,sample,review,rfCli,rfAgent,evalRun,evalSubmit,evalPoll,compare,sfPrepare,sfPropose,sfRender,sfParse,sfScoreCli,sfEval complete;
    class rawFlat,rawRun,pfRemote,pfLocal,pfTrash,staging,goldData,rfClassified,evalSidecar,evalRequests,evalResults,mismatches,runs,scored,sfTemplate,sfProposed,sfReviewMd,sfGold,sfRuns data;
    class skillsConfig,skillsProfile,skillsPrompt,sfRunner,dispatch future;
```

## Notes

- PII scrubbing and deduplication (SHA-256 of company + title + location) happen inside each scraper's `.scrape()` call — they are not separate pipeline stages.
- `--run-date YYYY-MM-DD` is optional on `run-config`, `prefilter`, and `remote-filter`. When provided, each stage reads/writes under a dated subdirectory. Without it, the legacy flat layout is used. Either way, explicit `--input`/`--output` flags override everything.
- The remote-filter HITL path samples production classifier output (`remote_filter_classified.jsonl` → `sample_for_review.py` → Streamlit review) into the gold dataset. The retired teacher bootstrap path (`prepare_batch` / `submit_batch` / `merge_batch_results`) is no longer part of the implemented data flow.
- Phase 3 (Skills Fit) — the Phase R eval harness consumes remote-filter records sampled into the seed pool. The Phase B production runner will consume both remote-filter classified records **and** local-candidate jobs from the prefilter — both are worth scoring against the candidate profile.
- The skills-fit candidate profile (`config/profile/candidate_profile.yml`) is part of the scoring contract, not just config: every skills-fit run record carries `profile_hash` + `profile_version` so runs aren't accidentally compared across profile changes. Bump `profile_version` (currently `2026-05-21-v4-draft`, with `education` as a top-level field) on every edit.
- Phase 4 (Dispatch) delivers the ranked shortlist from `data/scored/` via email or FastAPI web UI.
