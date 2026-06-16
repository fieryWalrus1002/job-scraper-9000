# Triage Funnel — navigation redesign

**Status:** Ratified 2026-06-15. Milestones: **Phase 16 — Triage Funnel:
Skeleton** and **Phase 17 — Triage Funnel: Swipe & Polish**.

## 1. Problem

The app's surfaces don't model the actual workflow. The main jobs list never
drops jobs you've triaged (`list_jobs` in `src/api/routes/jobs.py` never joins
`app.user_applications`), so trashed / shortlisted jobs keep reappearing. The
"pending" and "tracking" states are mashed into one WorkflowTab. There's no
home for trashed jobs and no way to rescue one. The result: triage doesn't
"stick," and there's no clear left-to-right sense of progress.

## 2. The funnel model

Conceptualize the workflow as a commitment funnel — a job moves rightward as it
earns more attention; trash is the sink to the left:

```
  TRASH   ◄──   JOBS   ──►  SHORTLIST  ──►  TRACKING
 passed       (no row)     maybe            to_apply, applied, screening,
                                            interview, offer, rejected,
                                            withdrew, hired, ghosted
```

Each tab is a **pure function of `app.user_applications.status`** — so "which
tab is this job in" is never ambiguous:

| Tab           | Status filter                   | Behavior                                                                                                                      |
| ------------- | ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **Trash**     | `passed`                        | un-trash clears the row → job falls back into Jobs                                                                            |
| **Jobs**      | *no* `user_applications` row    | the only untriaged surface; left=trash, right=Shortlist(`maybe`)                                                              |
| **Shortlist** | `maybe`                         | second-pass review of what you swiped in from Jobs — **Pursue** (→ Tracking) or **Trash**. Pure decision queue, nothing else. |
| **Tracking**  | `to_apply`, `applied` and later | the action board: To Apply (queued) → Active (in flight) → Closed                                                             |

Statuses (from `frontend/src/types.ts` / migration 0005): `maybe`, `to_apply`,
`applied`, `screening`, `interview`, `offer`, `rejected`, `candidate_withdrew`,
`hired`, `ghosted`, `passed`(Trashed).

## 3. Decisions

1. **Status→tab is the single source of truth.** No separate "is hidden" flag;
   tab membership is derived from status. This subsumes the old "hide triaged
   jobs from the main list" item — Jobs = untriaged by definition.
1. **Shortlist holds only `maybe`.** It's a pure second-pass decision queue:
   review what you swiped in from Jobs, then **Pursue** (promote `maybe → to_apply`, which moves the job to Tracking) or **Trash**. No sub-states.
1. **Tracking is a 3-group action board** *inside* the tab (not extra tabs):
   **To Apply** = `to_apply` (committed, not yet submitted — the action queue);
   **Active** = `applied`→`offer` (in flight); **Closed** =
   `rejected`/`ghosted`/`candidate_withdrew`/`hired`. Default shows To Apply +
   Active; Closed is collapsed so dead applications don't pile up in view.
1. **Reversibility is a first-class rule.** Every forward move has a cheap
   reverse: un-trash (Trash→Jobs), Shortlist→Jobs ("not interested") and
   Shortlist→Trash, Tracking→Shortlist ("didn't actually pursue").
1. **Trash is a top-level tab but visually de-emphasized** (far left, muted,
   count badge only when non-empty) — recovery surface, not a daily one.

### Resolved (ready to ratify)

- **Shortlist name** = *Shortlist*. ("Pending" rejected — collides with the
  pipeline `pending` blob container; alternatives Considering/Saved/Candidates
  set aside.)
- **Right-swipe** = `maybe` (lightest commitment). Keeps Jobs a fast binary.
- **`to_apply`** lives in **Tracking** as the To Apply queue, *not* in Shortlist.

## 4. Backend

Small — the data model already supports all of it.

- `list_jobs`: LEFT JOIN `app.user_applications`; default returns only rows with
  **no** status (untriaged). The funnel never needs `include_triaged` on this
  endpoint — triaged jobs live on the other tabs.
- Applications list endpoint (`src/api/routes/applications.py`): add a
  **status-set filter** param so Trash / Shortlist / Tracking are each one query
  over the same endpoint.
- Tests: each tab's query returns exactly its bucket; a status change moves a job
  between buckets.

## 5. PR slices — Phase 16 (Skeleton)

Ships the whole IA with plain controls (buttons, not gestures).

1. **BE:** `list_jobs` untriaged-only default (LEFT JOIN); tests.
1. **BE:** applications endpoint status-set filter; tests.
1. **FE:** 4-tab nav + routing (`/jobs`, `/shortlist`, `/tracking`, `/trash`).
   Jobs keeps `JobTable` (job-centric: Track column + context menu); the
   status tabs render a separate application-centric `TriageApplicationTable`
   (Status / Job / Score / Updated / Notes) since they show
   `user_applications` rows, not raw job summaries. *(Deviation from the
   original "reuse `JobTable`" note — the two row shapes differ; ratified in
   build, #261.)*
1. **FE:** Jobs feed = untriaged + click-to-set-status actions (Trash /
   Shortlist buttons on the row + detail panel).
1. **FE:** Shortlist tab — `maybe` only; second-pass review with a **Pursue**
   action (`maybe → to_apply`, moves the job to Tracking) plus Trash /
   back-to-Jobs.
1. **FE:** Tracking tab — 3 groups: To Apply (`to_apply`) / Active
   (`applied`→`offer`) / Closed; default shows To Apply + Active, Closed
   collapsed.
1. **FE:** Trash tab — `passed` + un-trash action; de-emphasized nav slot.
1. **FE:** pagination on the Jobs feed (wires existing `limit`/`offset`/`total`).

## 6. PR slices — Phase 17 (Swipe & Polish)

Makes it feel good. Each is independently shippable on top of the skeleton.

1. **FE:** swipe gestures on Jobs — left = Trash, right = Shortlist(`maybe`).
1. **FE:** undo affordance (snackbar) after any triage action.
1. **FE:** reversibility escapes wired across tabs (the §3.3 reverse moves).
1. **FE:** count badges on each tab (Trash badge only when non-empty).
1. **FE (optional):** keyboard shortcuts for triage (single-key trash/shortlist).

## 7. Out of scope

- Settings page / activity toggle / config schema fields → **Phase 18**.
- Posting readability (markdown, scraper formatting, add-job defaults) →
  **Phase 19**.
- Time-based events/tasks on Tracking applications (future; noted by the user).
- Bulk multi-select triage; saved views (backlog).
