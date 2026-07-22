# Spec: remote_filter model bake-off (quality × cost)

**Status:** RATIFIED (2026-07-21)
**Author:** Magnus
**Created:** 2026-07-21
**Related:** #63 (champion pin), #475/#476 (pricing config), `specs/remote_filter_classifier_tuning.md` (Phase 32)

## Purpose

A **repeatable procedure** for comparing candidate LLMs for the `remote_filter`
agent against the human-verified gold set, on **both quality and cost**, so a
champion swap is a measured decision instead of a vibe. Written so anyone can
re-run it when a new model ships. The mechanics generalize to `skills_fit`.

## Why now

We just pinned `gpt-5.4-mini` as champion (#63) and moved pricing into config
(#476). OpenAI now offers cheaper (`gpt-5.4-nano`) and stronger (`gpt-5.6-luna`,
`gpt-5.6-terra`) options. We also want historical continuity against the older
4o-era baselines and a real local llama.cpp check: if Qwen can hold quality on
this bounded classification task, it may be good enough at effectively zero API
cost.

## Decision record (grounded in the code, 2026-07-21)

1. **Pricing schema stays flat (`input` / `cached_input` / `output`).** OpenAI's
   Chat Completions `usage` object exposes cache *reads*
   (`prompt_tokens_details.cached_tokens`) but **no cache-*write* token count**
   (`remote_filter/utils.py:_extract_usage`). A `cache_write` price field would be
   unpopulatable — a schema that lies — so we do **not** add it. Long-context tiers
   only trigger above ~128K-token contexts; our inputs are single postings, so they
   never fire (YAGNI). GPT-5.6 models are added on the existing 3-field schema.
1. **Estimate vs actuals.** The eval cost is an *estimate* (observed tokens × list
   price). For GPT-5.6 it slightly **under-counts** the first-call cache-write
   premium (e.g. luna writes at $1.25 vs $1.00 input) — inherent and small. The
   invoice-accurate number comes from `src/utils/openai_costs.py` (org usage/costs
   API), not the estimator. Document the bias; don't chase it in the estimator.
1. **No LLM evaluation judge in the scored bake-off.** The 102-record human gold
   set is the authority for `remote_filter`. A model judge would be weaker, less
   reproducible, and an unnecessary layer between candidate predictions and known
   answers. LLM judges may help outside the scored benchmark — e.g. propose new
   edge cases, flag possible annotation mistakes for human review, or cluster
   failure patterns — but they do not decide pass/fail.
1. **Local models report zero API cost, not zero total cost.** llama.cpp/Ollama-
   compatible runs may still report tokens, but `$` cost in the bake-off is `0`
   because no OpenAI invoice is incurred. Wall-clock time, reliability, and local
   hardware opportunity cost are separate notes in the decision, not part of the
   `$ / correct` column.
1. **Decision metric = cost per correct classification**, reported *alongside*
   the Phase 32 champion pair (micro accuracy + `remote` recall). "Correct" means
   exact match against the human gold label; no fuzzy judge-mediated
   "acceptable" category. Cheapest model that holds quality wins; ties break on
   cost. `remote` recall is the guardrail — a cheaper model that drops real
   remote jobs is disqualified regardless of price.
1. **False negatives deserve first-class visibility.** False positives waste
   review time, but false negatives hide viable jobs entirely. The bake-off keeps
   `remote` recall as the hard guardrail and also reports remote false-negative
   and false-positive counts so the error shape is obvious without manually
   reading the confusion matrix.
1. **Bake-off rows must be comparable.** `compare_evals.py --bakeoff` should fail
   fast when selected rows mix gold hashes or prompt hashes. A same-table model
   bake-off only makes sense when candidates saw the same gold records and prompt.

## Prerequisites

- Gold set present: `data/eval/ground_truth.jsonl` (local-only, gitignored).
- Candidate OpenAI models priced in `config/pricing/openai.yml` (guard test
  enforces configured-agent coverage; bake-off candidates still need explicit
  entries for useful cost columns).
- Incumbent champion id in `config/eval/champions.yml`.
- For llama.cpp: router running on `http://localhost:8080/v1` (or set
  `OLLAMA_BASE_URL` accordingly) with the target model preset exposed.

## Candidates (first bake-off)

| Provider                        | Model           | Role                          | Rationale                                                                                                     |
| ------------------------------- | --------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------- |
| OpenAI                          | `gpt-5.4-mini`  | champion (incumbent)          | current pin (#63)                                                                                             |
| OpenAI                          | `gpt-5.4-nano`  | cheap challenger              | ~73% cheaper; bounded classification fits nano                                                                |
| OpenAI                          | `gpt-5.6-luna`  | strong challenger             | +33% vs mini; test if quality lift justifies it                                                               |
| OpenAI                          | `gpt-5.6-terra` | quality reference             | upper bound / escalation benchmark                                                                            |
| OpenAI                          | `gpt-4o-mini`   | historical baseline           | older production-era baseline, already priced                                                                 |
| OpenAI                          | `gpt-4.1-nano`  | cheap non-reasoning reference | current priced nano model in the 4.x table; useful sanity check if we want an ultra-cheap non-GPT-5 reference |
| llama.cpp via `ollama` provider | `qwen-27b-mtp`  | local challenger              | current Qwen 3.7-ish 27B MTP preset in the llama.cpp router; zero API cost if quality holds                   |

`gpt-4o-nano` is **not** listed in the 2026-07-21 saved OpenAI pricing page
(`notes/api-pricing/Pricing OpenAI API - developers.openai.com.md`). The current
4o entries there are `gpt-4o`, `gpt-4o-mini`, and `gpt-4o-2024-05-13`; the
current priced nano entry in that area of the table is `gpt-4.1-nano`. Do not add
or run `gpt-4o-nano` unless an API/model-list check proves it exists.

## Operational finding: the local model is a quality/cost anchor, not a pipeline engine

Measured on the 2026-07-21 smoke run (`qwen-27b-mtp`, 102-record gold, `--workers 1`):

- **Quality/cost:** 99.0% micro accuracy, 1.00 `remote` recall, `$0` API cost. A
  local 27B reasoning model *can* match API-tier quality at zero marginal dollar
  cost — a useful upper bound and a $0 floor for the cost axis.
- **Throughput:** ~28s/call (it emits a ~2,700-token reasoning trace per job),
  ≈ **2.1 jobs/min**, GPU-bound. Wall-clock equalled the summed per-call latency
  (0% idle), so the single llama.cpp slot was saturated the whole time. Extra
  eval `--workers` or parallel slots do **not** help — they split the same
  ~90 tok/s aggregate. A 1,000-job cold run ≈ **8 hours at 100% GPU**.

**Decision:** the local model is an **eval-time quality-and-cost anchor**, not the
pipeline classifier. The `AnalysisCache` means steady-state runs only re-analyze
new/unseen jobs (and the cache is shared across users), so the 8-hour figure is a
cold-start / backfill / model-swap cost rather than a per-run tax — but it still
can't be bursted on one GPU, so it's unusable as production throughput. The
pipeline champion stays an API model (sub-second, horizontally scalable); the
local run exists to tell us exactly what quality/$ we trade for that throughput.

## Procedure (the repeatable runbook)

```bash
# 0. One-time: ensure OpenAI candidates are priced (guard test is the gate)
#    edit config/pricing/openai.yml, then:
uv run pytest tests/utils/test_pricing_config.py tests/utils/test_openai_pricing.py

# 1. Run the eval once per OpenAI candidate. --model overrides YAML in-memory;
#    --run-id labels the run so it's identifiable in runs.jsonl.
OPENAI_MODELS=(
  gpt-5.4-mini
  gpt-5.4-nano
  gpt-5.6-luna
  gpt-5.6-terra
  gpt-4o-mini
  gpt-4.1-nano
)

for M in "${OPENAI_MODELS[@]}"; do
  uv run scripts/run_remote_filter_eval.py \
    --provider openai --model "$M" --temperature 0.0 --workers 4 \
    --run-id "bakeoff_${M//./}"
done

# 2. Run the local llama.cpp candidate. The code path is named "ollama" because
#    llama.cpp exposes an OpenAI-compatible endpoint and this project already
#    routes local OpenAI-compatible servers through that provider value.
OLLAMA_BASE_URL=http://localhost:8080/v1 \
uv run scripts/run_remote_filter_eval.py \
  --provider ollama --model qwen-27b-mtp --temperature 0.0 --workers 4 \
  --run-id bakeoff_qwen27b_mtp

# 3. Tabulate quality × cost across the runs. This should fail fast if the
#    selected rows do not share the same gold_hash and prompt_hash.
uv run scripts/compare_evals.py --bakeoff --last 7

# 4. Inspect mismatches for any candidate that regresses remote recall.
#    data/eval/mismatches_<run_id>.jsonl

# 5. Decide: cheapest model holding micro accuracy + remote recall wins.
#    To promote, update config/eval/champions.yml (PR) and the agent's
#    config/agent/remote_agent.yml model (separate PR).
```

The saved pricing page does not list `gpt-4o-nano`; use `gpt-4.1-nano` for the
current cheap 4.x nano reference instead. If a future API/model-list check proves
`gpt-4o-nano` exists, add it only with verified pricing.

## Machinery to build (this effort)

1. **Cost + latency capture in `run_remote_filter_eval.py`.** The eval calls
   `analyze_remote(rf_input, llm_config=...)` and previously discarded usage.
   Wire a `usage_callback` (mechanism already exists — `remote_filter/utils.py`,
   used by the prod runner), aggregate token totals, call `estimate_cost(model, ...)`, and add a `cost` block to the printed report and runs.jsonl record.
   - Provenance gains: top-level `token_totals`, top-level `cost` block with
     `estimated_cost_usd`, `$/record`, `$/correct` (cost ÷ exact gold matches),
     `breakdown`, and `pricing_note`.
   - Local/ollama-compatible providers store `estimated_cost_usd: 0.0` and
     `pricing_note: local_provider_zero_api_cost`.
   - Persist enough timing summary to compare local vs API operationally (average
     and/or p95 latency), but latency is not part of the champion metric.
1. **Bake-off view in `compare_evals.py`.** Existing `--diff` is pairwise; add an
   N-way `--bakeoff` table: `model | micro_acc | remote_recall | remote_fn | remote_fp | macro_f1 | skipped/failed | est_cost | $/correct`, sorted by
   `$/correct`, champion row flagged. Fail fast if selected rows mix gold hashes
   or prompt hashes.
1. **Pricing entries.** Add `gpt-5.4-nano`, `gpt-5.6-luna`, `gpt-5.6-terra`, and
   `gpt-4.1-nano` to `config/pricing/openai.yml` (standard short-context rates)
   with a comment noting the 5.6 cache-write estimate caveat + pointer to
   `openai_costs.py` for actuals. `gpt-4o-mini` is already priced. Do not add
   `gpt-4o-nano` unless a current source verifies it exists.
1. **Docs.** This spec is the durable runbook. Refresh the scattered/stale bits:
   `src/agents/remote_filter/README.md` "Eval workflow" (point here), and
   `scripts/README.md` (fix stale `gpt-4o-mini` default → `gpt-5.4-mini`, mention
   cost capture and `--bakeoff`).

## PR slices

- **Slice 1** — pricing entries for nano/luna/terra + guard-test coverage.
- **Slice 2** — cost/timing capture in `run_remote_filter_eval.py` (+ provenance
  fields, report line, unit test on aggregation and local zero-cost behavior).
- **Slice 3** — `compare_evals.py --bakeoff` N-way table (+ comparable-run guard,
  remote FP/FN + skipped/failed visibility, test).
- **Slice 4** — docs: this spec + README/scripts refresh.
- *(then run the bake-off, record results here, and decide champion in a follow-up)*

## Out of scope

- Invoice-accurate 5.6 cost (cache-write / long-context) — actuals via
  `openai_costs.py`, not the estimator. Only if a decision hinges on it.
- Local model performance tuning (prompt forks, llama.cpp sampling sweeps, router
  concurrency tuning). First pass uses the production prompt and temperature 0.0.
- `skills_fit` bake-off — same mechanics, separate effort (ordinal metrics + kappa).
- LLM-as-judge scoring for this bake-off. Human gold labels are primary; judges
  are allowed only as supplementary analysis outside the scored benchmark.
- ~~Weighted-error metric automation.~~ **Shipped (#545):** `--bakeoff` now
  reports a `weighted_error` scalar from a per-confusion-cell cost matrix
  (`config/eval/remote_filter_error_costs.yml`), computed at compare-time from
  each run's stored confusion, with `--rank weighted_error` and the matrix hash
  surfaced for auditability. Raw `remote_fn`/`remote_fp` stay visible; it is an
  additive lens, not a replacement for the champion metric pair. Tuning the
  weight values remains out of scope (a separate calibration).
- Automated champion promotion — stays a human PR decision.

## Changelog

- 2026-07-21 — initial draft.
- 2026-07-21 — added historical 4o baselines and llama.cpp/Qwen local challenger to the runbook.
- 2026-07-21 — ratified: human gold set only (no eval judge), exact-match
  `$/correct`, local zero API cost, comparable-run guard, and remote FP/FN
  visibility.
- 2026-07-21 — verified current saved OpenAI pricing page: no `gpt-4o-nano` row;
  use `gpt-4.1-nano` as the current priced nano reference.
- 2026-07-22 — shipped the weighted-error lens (#545): compare-time
  `weighted_error` from a config cost matrix, `--rank weighted_error`, matrix hash
  in the bake-off output. Moved from Out-of-scope to done.
- 2026-07-22 — recorded operational finding from the local smoke run: `qwen-27b-mtp`
  hits 99% micro / 1.0 remote recall at $0 but only ~2.1 jobs/min (GPU-bound),
  so the local model is an eval-time quality/cost anchor, not the pipeline classifier.
