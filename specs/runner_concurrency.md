# Runner concurrency: thread-pool the per-job LLM calls

**Status:** RATIFIED 2026-07-07. Milestone **Phase 27: Runner concurrency**;
slices #441 / #442 / #443.

**Related, explicitly deferred:** #440 (abort the run on unrecoverable LLM
errors like `insufficient_quota` instead of retrying per job). Concurrency does
not regress that behavior, but it does mean a quota-dead account burns through
doomed calls `max_workers`× faster in wall-time. It is a separate small PR
against both agents' retry loops and stays out of these slices to keep them
behavior-preserving.

## Changelog

- **2026-07-07 — ratified.** Promoted from the orchestration plan at
  `notes/orchestrate/runner-concurrency/` (local-only; the plan's briefs remain
  the per-slice working instructions). Incorporates the pre-dispatch review
  fixes: pool teardown must cancel queued futures, and failure semantics are
  `analysis is None` in the sink (the `analyze_*` functions never raise).

## 1. Problem

Both LLM agent runners process jobs in a strictly sequential loop:

- `run_remote_filter` (`src/agents/remote_filter/runner.py`, ~L163): one
  blocking `analyze_remote()` call per job.
- `run_skills_fit` (`src/agents/skills_fit/runner.py`, ~L340): one blocking
  `analyze_skills_fit()` call per job.

Each call is ~3s of almost pure network wait (OpenAI round-trip). Observed
2026-07-06: a 1349-job remote_filter pass took **~1h26m**. The work is
embarrassingly parallel — nothing about job N depends on job N-1 — so the
latency is all queueing, not compute. The OpenAI SDK releases the GIL during
the wait, so plain threads give near-linear speedup; at 8 workers the same run
targets **~8–9 min**. No async rewrite is needed or wanted.

## 2. Design

One shared primitive plus a three-phase restructure of each runner's loop. The
invariant that makes this safe **without any locks**: every piece of shared,
non-thread-safe state stays on the main thread; only the pure network call
enters the pool.

Confirmed non-thread-safe state (all plain `+=` / `.append` / file writes):

- `RunTracker.add_token_usage` / `record_call_latency` / `increment_failures`
  (`src/utils/run_tracker.py` ~L338–363)
- `AnalysisCache.put` (append to JSONL)
- output sinks: remote_filter's `pass_f`/`trash_f` handles; skills_fit's
  in-memory `enriched_records` list
- all counters (`passed`/`failed`/`skipped`/`cache_hits`/`cache_misses`/…)

### 2.1 Shared helper — `src/utils/concurrent.py` (#441)

```python
def imap_unordered(work, items, *, max_workers) -> Iterator[tuple[T, R]]
```

Maps a blocking callable over items on a bounded `ThreadPoolExecutor`, yielding
`(item, result)` pairs **as they complete** (unordered). Design points:

- **Teardown uses `shutdown(wait=True, cancel_futures=True)` in a
  `try/finally`, not a bare `with ThreadPoolExecutor` block.** All items are
  submitted up front; the context manager's `__exit__` does not cancel pending
  futures, so on a failure or Ctrl-C it would block until the *entire queue*
  ran to completion (for a 1349-job run, potentially the better part of an
  hour of zombie API spend). `cancel_futures` drops the queue and waits only
  on the ≤ `max_workers` calls in flight. The `finally` also covers a consumer
  abandoning the generator early.
- Exceptions from `work` propagate to the caller (fail fast) — never swallowed.
- Deliberately dumb: no async, no external deps, no retry or rate-limit logic
  (retries live in the agents' `utils.py`).

Extracting a shared base rather than copy-pasting the pool into two runners
follows the `analysis_cache` precedent (CLAUDE.md, Caching + dedup).

### 2.2 Runner restructure — three phases (#442 remote_filter, #443 skills_fit)

1. **Plan pass (main thread).** Iterate jobs; handle inline exactly as today
   anything that never needs a call: missing-description skips, and for
   skills_fit the resume-from-existing-output records. `cache.get` for the
   rest; partition into *hits* (analysis in hand) and *misses* (need a call).
   Cache-miss accounting stays at lookup time, as today.
1. **Concurrent pass.** For misses only, a `work()` closure calls `analyze_*`
   with `usage_callback` redirected to a **fresh per-call local dict**
   (`lambda u: usage.update(u)`) — never `run.add_token_usage` from a worker
   thread — and returns `(analysis, usage, elapsed)`. Fan out via
   `imap_unordered(work, misses, max_workers=max_workers)`.
1. **Sink (main thread).** For hits and completed misses, do exactly today's
   post-analysis work: apply token usage + call latency to the `RunTracker`
   (misses only), `cache.put` (misses with non-None analysis), the policy
   gate / score build, output write, counters, PASS/TRASH logging.

Behavior is identical to today — same outputs, cache entries, counts, token
totals, cost — except speed and the order results complete. Incremental
cache-writes and partial-progress-on-crash (the resume story) are preserved.

### 2.3 Failure and interrupt semantics

- `analyze_remote` and `analyze_skills_fit` **never raise** — both catch all
  exceptions internally and return `None` after retries
  (`remote_filter/utils.py` ~L225–247; `skills_fit/utils.py` ~L161–186).
  Per-job failure therefore arrives in the sink as `analysis is None` and is
  handled exactly as today (skip + `increment_failures()` + warning). No
  try/except belongs around the pool for per-job errors; only programmer
  errors propagate from `imap_unordered`, and they should (fail fast).
- skills_fit's interrupt path (partial write of `enriched_records`,
  runner ~L423–426) keeps working by construction: `KeyboardInterrupt`
  surfaces from the main-thread consuming loop, and the helper's teardown
  cancels queued futures.

### 2.4 Ordering (skills_fit only)

Unordered completion may reorder `enriched_records` relative to input.
remote_filter is unaffected (pass/trash JSONL order was never meaningful).
For skills_fit, #443 must either confirm nothing downstream depends on input
order or stabilize-sort before `write_output` (e.g. by `dedup_hash` or a
captured input index) — and document which in the PR.

## 3. Configuration

`max_workers` is non-secret config → YAML, per agent, in the existing `llm:`
block (it is a property of how we call the provider):

- `config/agent/remote_agent.yml` → `llm.max_workers: 8`
- `config/agent/skills_fit.yml` → `llm.max_workers: 8`

Read as `int(llm_config.get("max_workers", 8))`. Default 8 is conservative for
gpt-4o-mini at a normal usage tier; genuine rate-limit 429s are transient and
already handled by the in-agent retries. Local `ollama`/llama.cpp endpoints can
set it lower (or 1) if the local server serializes anyway.

## 4. PR slicing

| Slice                                            | Issue | Base branch                  | Scope                                                                  |
| ------------------------------------------------ | ----- | ---------------------------- | ---------------------------------------------------------------------- |
| `feat(utils)`: `imap_unordered` + tests          | #441  | `main`                       | helper + `tests/utils/test_concurrent.py` only                         |
| `perf(remote_filter)`: concurrent classification | #442  | `feat/441-concurrent-helper` | runner restructure + `remote_agent.yml` knob + tests                   |
| `perf(skills_fit)`: concurrent scoring           | #443  | `feat/441-concurrent-helper` | runner restructure + `skills_fit.yml` knob + ordering decision + tests |

#442 and #443 touch disjoint files and run in parallel. #443 is the
lower-value half (post-filter batches are smaller) and is droppable or
deferrable without affecting the other two.

Working briefs (per-slice ground truth, acceptance criteria, do-NOT fences)
live in `notes/orchestrate/runner-concurrency/` — local-only, not committed.

## 5. Verification

Per slice: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` — plus, for #441, unit tests covering pairing,
empty input, exception propagation **with queued-future cancellation**, and a
non-flaky wall-clock concurrency assertion. For #442/#443, existing runner
tests must pass unchanged (same counts/outputs for same inputs) plus a
non-flaky test that concurrency is actually wired.

## 6. Explicitly out of scope

- #440 — unrecoverable-error fast-abort in the retry loops (see header).
- OpenAI Batch API (~50% cheaper, minutes-to-24h async) — the parked Phase 13
  batch slices (#203 et al.). Right tool for cost, wrong tool for interactive
  latency; unaffected by this work.
- Any change to prompts, schemas, cache keys, policy gates, or retry logic.
