# Eval Correction Workflow

Written 2026-06-03. Durable spec for the `skills_fit` correction UX.

## Purpose

Build a gold dataset for `skills_fit` incrementally from dashboard usage. When the user spots a wrong AI score in `JobDetailPanel`, they flag it with the correct score + a short reason. Corrections export as JSONL that feeds the eval harness.

Complements `scripts/propose_skills_fit_seed.py`:

| Source                         | Pattern                           | Bias                                               |
| ------------------------------ | --------------------------------- | -------------------------------------------------- |
| Proposal-seed script           | Sampled batch, teacher-first HITL | Lower-bias, structured                             |
| Eval correction UX (this spec) | Real-usage signal, ad-hoc         | Higher-bias, reflects what the user actually reads |

Both feed the same evaluator, same JSONL format.

## Data model

`app.eval_corrections` — one row per `dedup_hash`, last-write-wins.

```sql
CREATE TABLE app.eval_corrections (
  dedup_hash        TEXT PRIMARY KEY,
  corrected_score   INT NOT NULL CHECK (corrected_score BETWEEN 1 AND 5),
  correction_reason TEXT,
  original_score    INT,
  original_model    TEXT NOT NULL,
  profile_version   TEXT NOT NULL,
  corrected_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON app.eval_corrections (original_model, profile_version);
```

**Why snapshot `original_score`, `original_model`, `profile_version`:** a correction is scoped to a specific `(model, profile_version)` pair — what "correct" means changes when the profile changes, and the original score is meaningful only relative to the model that produced it. Snapshotting at correction time decouples the correction from later re-scoring runs.

**Why UPSERT (last-write-wins) over a versioned history:** MVP simplicity. Multi-version history can be added later by switching the PK to `(dedup_hash, corrected_at)` if we ever want to study label drift.

## Phased delivery — three small PRs

### PR 1 — Backend (storage + API)

Self-contained backend slice. No frontend changes. No conflict with the in-flight Tailwind polish PR.

- Alembic migration `migrations/versions/0004_create_app_eval_corrections.py`
- Pydantic models in `src/api/schemas.py`:
  - `EvalCorrectionIn` (request body for upsert)
  - `EvalCorrectionOut` (response)
- Routes (in `src/api/main.py`, or split to `src/api/eval.py` if main is getting unwieldy):
  - `POST   /api/eval/corrections` — upsert
  - `GET    /api/eval/corrections/{dedup_hash}` — read, 404 on miss
  - `DELETE /api/eval/corrections/{dedup_hash}` — clear
  - `GET    /api/eval/corrections?model=X&profile_version=Y` — list (used by PR 3)
- Tests: round-trip upsert/read/delete; constraint check on `corrected_score`

### PR 2 — Frontend (wire the JobDetailPanel placeholder)

**Needs the polish PR merged first** — both touch `frontend/src/components/JobDetailPanel.tsx`. Branching from main for PR 2 before polish lands will cause a merge conflict.

- `useEvalCorrection(dedupHash)` React Query hook (read) and `useSetEvalCorrection` / `useDeleteEvalCorrection` mutation hooks (mirror `useApplications`)
- `EvalCorrectionSection` component replaces the placeholder section in `JobDetailPanel.tsx`:
  - 1–5 score selector — chip row matching existing score badge styling
  - "Reason" textarea (short, optional)
  - Save / Clear buttons (shadcn `Button`)
- Visual signal on the panel header when a correction exists — small "corrected" badge next to the AI score
- OpenAPI types regen if Phase 2.5 codegen is wired by then; otherwise hand-add to `frontend/src/types.ts`
- **Expose `dedup_hash` in the Dev Metadata section.** Currently hidden — only `model`, `provider`, `profile_version`, `run_id`, `scored_at`, `ingested_at`, `source`, `source_job_id` are shown. Without `dedup_hash` visible, manual API testing (curl against `/api/eval/corrections`) requires grep-ing JSONL files to find a real hash. Add `['Dedup hash', data.dedup_hash]` to the metadata list, ideally with click-to-copy.

### PR 3 — Export script + eval-harness handshake

- `uv run scripts/export_eval_corrections.py --model X --profile-version Y`
- Reads `app.eval_corrections` filtered by `(model, profile_version)`
- Joins with `raw.scored_job_postings` for title/description/etc. needed by the eval harness
- Emits JSONL in the existing gold-set format (need to read `src/agent_eval/` first to nail the exact shape — verify when starting this PR)
- Output to `data/eval/corrections_gold.jsonl` or wherever the existing gold sets live
- Short README note on the two correction sources (proposal seed vs dashboard usage)

## Out of scope (defer until needed)

- Corrections review UI (tab showing all corrections, edit/delete in bulk) — build when corrections count justifies it
- Multi-version history per `dedup_hash` — only if studying label drift becomes interesting
- Auto-stale detection (flag when underlying `(model, profile_version)` has changed since correction) — defer until it causes confusion

## Open questions for PR 3

- Exact JSONL shape expected by `src/agent_eval/` — read the existing gold files and harness entry point before writing the exporter
- Whether corrections JSONL merges with proposal-seed JSONL or stays separate

## Dependencies + ordering

- PR 1 → independent, can start immediately (no overlap with in-flight polish PR)
- PR 2 → wait for polish PR merge (shared file)
- PR 3 → needs PR 1 merged; independent of polish PR
