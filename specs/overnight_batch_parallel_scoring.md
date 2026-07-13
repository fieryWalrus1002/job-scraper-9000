# Overnight `--batch`: submit-all-then-poll-all per-user scoring

Status: **ratified.** Follow-up to PR #462 (`overnight --batch`); tracked as issue #463.

## 1. Problem

`overnight --batch` routes the two LLM phases through the OpenAI Batch API. Classification
is fine: `run_remote_filter_batch` submits **one global batch** for the whole consolidated
union. Scoring is not: `score_run` (`src/pipeline/scoring.py`) loops users **serially**, and
`run_skills_fit_batch` (`src/agents/skills_fit/batch.py`) is a monolith — build requests →
submit → **poll until terminal** → download → write — all inside one call. So with two
users, user B's batch is not even *submitted* until user A's batch has fully completed.

Total scoring wall time is the **sum** of per-user batch turnarounds instead of the **max**.
Each batch carries a 24h completion SLA, so the tail risk stacks linearly with user count:
2 users = 48h worst case, and every new user pushes it out further. Typical turnarounds are
minutes-to-an-hour, so this is tolerable at 2 users — but it is the wrong shape, and it gets
strictly worse with growth.

**Goal:** in batch mode, submit every user's skills_fit batch up front, then poll them all
together and collect each as it finishes. Wall time becomes max-of-batches. Per-user failure
isolation (Phase 13 spec §7) must hold in both phases.

## 2. Current state — code anatomy

- **`run_skills_fit_batch`** (`src/agents/skills_fit/batch.py:186`) — three stages inside
  one `RunTracker` context:
  1. *Local pass*: load + merge + dedup inputs, reuse existing output rows, skip
     missing-description rows, serve cache hits; queue cache-miss requests + a `plan` of
     pending entries.
  1. *Submit + block*: `_write_request_file` → `upload_and_create_batch` →
     `poll_until_done` → `download_results`.
  1. *Resolve*: map results back by `custom_id`, `cache.put` successes, build enriched
     records (incl. `agent_failed` rows), `write_output`, then the `finally` block records
     outputs/cache/cost telemetry on the tracker.
- **`score_run`** (`src/pipeline/scoring.py:297`) — per-user loop: policy-gate the
  classified union, write the user's `input.jsonl`, call the injected `score_fn`
  (one-shot, returns a summary dict), `_stamp_user_email`, accumulate the run summary.
  Per-user try/except gives failure isolation.
- **`utils/batch_api.py`** — shared primitives: `upload_and_create_batch`,
  `poll_until_done` (single batch id), `download_results`.
- **`batch_score_fn`** (`src/pipeline/scoring.py`) — the #462 hook twin; today it just
  calls the monolith, which is where the serial blocking comes from.

The seam already exists: `run_overnight` takes injectable `classify_fn`/`score_fn`, and the
CLI swaps in batch twins under `--batch`. This design changes what the scoring twin does,
not where it plugs in.

## 3. Design

### 3.1 `utils/batch_api`: multi-batch poller

```python
def poll_all_until_done(
    client, batch_ids: list[str], poll_interval: int = 60
) -> dict[str, Batch]:
    """One poll loop over many batches; returns {batch_id: terminal Batch}."""
```

Single loop, one `client.batches.retrieve` per outstanding id per tick, drops ids as they
reach a terminal state, logs progress per tick (`n of m terminal`). `poll_until_done`
becomes the `len == 1` case (or stays as-is; it's three lines either way). No concurrency —
this is still one thread, just interleaved waiting.

### 3.2 Split the skills_fit batch runner into submit + collect

`run_skills_fit_batch` splits into two functions plus a state handle:

```python
@dataclass
class SkillsFitBatchSubmission:
    run: RunTracker            # entered, not yet exited
    batch_id: str | None      # None ⇒ nothing needed the API (all served locally)
    client: Any | None
    plan: list[dict]           # pending entries, keyed by custom_id
    enriched_records: list[dict]  # rows already resolved locally (cache/resume/skip)
    counters: ...               # cache_hits/misses, resumed, skipped, submitted, …
    output_path: Path
    cache: AnalysisCache
    build_metadata: Callable[..., dict]
    summary_inputs: ...         # everything the final summary dict needs

def submit_skills_fit_batch(**kwargs) -> SkillsFitBatchSubmission: ...
def collect_skills_fit_batch(
    submission: SkillsFitBatchSubmission, batch: Batch | None
) -> dict[str, Any]: ...
```

- **`submit_…`** = stages 1 + the submit half of 2 (through `upload_and_create_batch`).
  Same kwargs as today's `run_skills_fit_batch`. Returns immediately after submission —
  never polls. If the local pass leaves nothing to submit, `batch_id is None` and collect
  skips straight to writing.
- **`collect_…`** = the download + resolve + write + telemetry-`finally` half. Takes the
  terminal `Batch` object (the caller polled), enforces `status == "completed"` (else
  `_log_batch_failure` + raise, as today), and **closes the tracker** on every path.
- **`run_skills_fit_batch` stays** as a thin composition — submit → `poll_until_done` →
  collect — so the agent's standalone `--batch` CLI and #462's single-user semantics are
  byte-for-byte unchanged, and the split is testable in isolation.

**RunTracker lifetime is the sharp edge.** Today one `with` block spans the whole run;
after the split the tracker is entered in submit and exited in collect. The submission
handle owns it, and gets an `abort(exc)` method (exit the tracker with the exception) so a
user whose batch fails/expires — or whose collect raises — still writes a complete,
failure-marked run record instead of leaking an open tracker. Every submission must end in
exactly one of `collect_…` or `abort(…)`; `score_run`'s phase-2 loop guarantees this.

### 3.3 `score_run`: two-phase fan-out in batch mode

`score_run` gains an optional two-phase seam alongside the existing one-shot `ScoreFn`:

```python
class BatchScoreFns(NamedTuple):
    submit: SubmitFn    # same kwargs as ScoreFn → SkillsFitBatchSubmission
    collect: CollectFn  # (submission, batch) → summary dict

def score_run(conn, *, run_id, run_date, runs_dir,
              score_fn: ScoreFn = default_score_fn,
              batch_score_fns: BatchScoreFns | None = None) -> dict[str, Any]: ...
```

When `batch_score_fns` is provided the per-user loop runs twice:

1. **Submit phase** — existing gating code unchanged (policy gate, survivors, `input.jsonl`,
   profile check), then `submit(...)` instead of `score_fn(...)`. Per-user try/except as
   today: a submit failure marks that user failed and the loop continues. Users with no
   survivors are skipped exactly as now (nothing submitted).
1. **Poll once** — `poll_all_until_done(client, [s.batch_id for pending])` over every
   submission with a real `batch_id`. One shared client (all submissions resolve the same
   provider config; batch mode is OpenAI-only).
1. **Collect phase** — for each submission in user order: `collect(submission, batch)` →
   `_stamp_user_email` → accumulate summary. A failed/expired batch or a collect exception
   fails **only that user** (`submission.abort(exc)` + traceback logged + `failed` in the
   summary), matching spec §7 isolation. If `poll_all_until_done` itself raises (network
   death), every pending submission is aborted and all those users are marked failed — the
   run summary's all-failed verdict handles the morning-after messaging.

The summary dict shape (`users_scored`, `users_failed`, `per_user`, …) is unchanged, so
`pipeline/summary.py` needs no changes.

`pipeline/scoring.py`'s `batch_score_fn` from #462 is replaced by a `BatchScoreFns` pair
wrapping `submit_skills_fit_batch` / `collect_skills_fit_batch`; `overnight.py` passes it
as `batch_score_fns` under `--batch`. The CLI surface (`--batch`) does not change.

### 3.4 Interrupts and crashes

If the run dies between submit and collect, the OpenAI batches keep running server-side.
The batch ids and request files are already logged/persisted at submit
(`data/batch/skills_fit_requests_<run_id>.jsonl`), so the failure is auditable. A re-run
re-submits from scratch — the analysis cache is only populated at collect, so nothing is
reused from an uncollected batch. Cross-run batch **resume** (re-attach to a live batch id)
is explicitly out of scope; at current volume the wasted batch is cents.

## 4. Not doing

- **Parallelizing the serial (live-call) path** — different problem (per-call latency, not
  submission serialization), different risks (cache/tracker concurrency). Not touched.
- **Threads** — a `ThreadPoolExecutor` over the existing monolith would be a smaller diff
  but puts concurrent writers on the append-only `AnalysisCache` JSONL and `RunTracker`,
  neither of which was written for it. Rejected in the #462 discussion.
- **remote_filter changes** — already one global batch.
- **Batch resume across interrupted runs** — see §3.4.

## 5. PR slicing

1. **`poll_all_until_done`** in `utils/batch_api.py` + unit tests (fake client, mixed
   terminal states, per-tick logging).
1. **Submit/collect split** of `src/agents/skills_fit/batch.py`: `SkillsFitBatchSubmission`
   (+ `abort`), `submit_…`, `collect_…`, `run_skills_fit_batch` re-expressed as their
   composition. Behavior-preserving — existing batch tests keep passing, new tests cover
   the handle lifecycle (collect closes tracker; abort closes tracker with failure).
1. **Two-phase `score_run`** + `BatchScoreFns` + overnight wiring; tests for submit-phase
   isolation, collect-phase isolation, poll-death ⇒ all pending users failed, and unchanged
   summary shape. Serial path untouched (existing tests prove it).

## 6. Changelog

- 2026-07-08 — drafted following PR #462 review discussion (serial per-user polling).
- 2026-07-13 — ratified. Refreshed `score_run` line ref (242 → 297) after #465's
  location-aware gate landed on `main`.
