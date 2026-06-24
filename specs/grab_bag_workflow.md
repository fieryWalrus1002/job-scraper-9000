# Grab-bag triage workflow & swipe parity

**Status:** Draft proposal (uncommitted) — 2026-06-24. All forks resolved (§3.1)
and §8 defaults confirmed by the user (floor 3, batch 20, phased nav flip).
Phasing split into two milestones (§6): Phase 24 swipe parity, Phase 25 grab bag.
Ready to ratify → commit → cut milestones + issues.

## 1. Problem

The Jobs tab — the entry point to the funnel — is a sortable, filterable,
paginated **database table** (`JobTable.tsx`, 50 rows/page, `ORDER BY fit_score DESC`). It was built for "look at ALL the jobs and search through them."

But the workflow has moved on. With swipe triage (`useRowSwipe`) and the
activity timeline, the day-to-day act is **triage**, not browsing: surface a
handful of strong matches, judge each one, move on. A full sortable table is the
wrong primary surface for that — it invites scanning and re-scanning the same
ordering instead of making fast decisions on a fresh, motivating set.

Two gaps, separable:

1. **Swipe is table-only.** `useRowSwipe` is a standalone, surface-agnostic hook,
   but only `JobTable` rows use it. The card surfaces (Shortlist, Tracking,
   Trash via `TriageApplicationTable` / `TrackingBoard`) have no swipe.
1. **The primary surface is a browse tool, not a triage tool.** There is no
   "give me a fresh batch of strong matches to decide on" mode.

## 2. What exists today

- **Jobs** = `JobTable.tsx`: sortable (whitelisted columns, deterministic
  tiebreaker), filterable (`FilterPane`), paginated (`useJobs(filters, page, sort)` → `GET /jobs?…&limit=50&offset=…`). Has swipe + keyboard triage.
- **Shortlist / Tracking / Trash** = card-style surfaces, **no swipe**.
- **`useRowSwipe.ts`** — gesture-agnostic: returns `offset`/`progress`/`armed`/
  `direction` + pointer `handlers` to spread onto *any* element. Already
  decoupled from the table row.
- **`fit_score`** — per-user 1–5 ordinal (`FitScore = Literal[1,2,3,4,5]`),
  joined from `raw.job_scores`; `NULL` when a job is unscored.
- **`untriagedJobs`** (App.tsx) — the Jobs feed already excludes any job with an
  application row (shortlisted/tracked/trashed). The grab bag draws from exactly
  this pool.
- **Settings** — typed columns on `app.user_search_configs`, surfaced via
  `SettingsResponse`, written via dedicated `*Update` endpoints
  (`extra: "forbid"`, `Field(ge=…)`). The alert-thresholds migration (`0013`) is
  the template. Latest migration is `0015`.

## 3. The design

Two tracks. Track A (swipe parity) is independent and ships value alone; Track B
(grab bag) builds on it.

### 3.1 Resolved forks

- **Selection: weighted-by-fit.** Not pure top-N (deterministic, goes stale) and
  not uniform-random (ignores quality). Sample from the untriaged, above-floor
  pool with probability biased toward higher `fit_score`, so every reroll is
  fresh *and* surfaces strong-but-not-#1 jobs.
- **Batch model: stateless + seed.** No new tables, no session state. A batch is
  a seeded random query excluding already-triaged jobs. The seed makes it stable
  within a batch (refresh ≠ reshuffle); "New batch" = a new seed.
- **Card UI: column/grid of N swipeable cards.** Not literal one-card Tinder —
  job search needs side-by-side comparison. ~N cards visible, each a swipe
  target, reusing Track A's gesture.

### 3.2 Weighted sampling (the core mechanic)

Efraimidis–Spirakis weighted sampling-without-replacement, expressed as a pure
stateless SQL `ORDER BY … LIMIT n`. Each candidate row gets a key
`u^(1/weight)`; take the top `n` by key. With `weight = fit_score`, the
selection probability is proportional to fit — higher-scored jobs are *more
likely* to appear, but not guaranteed, so rerolls vary.

`u` must be a **deterministic** per-(row, seed) uniform in `(0,1]` so a batch is
stable across refreshes:

```sql
-- u in (0,1] derived from (dedup_hash, seed); same seed ⇒ same batch
WITH scored AS (
    SELECT a.dedup_hash, s.fit_score,
           ((abs(hashtextextended(a.dedup_hash, %(seed)s)) % 1000000) + 1)
               / 1000000.0  AS u
    FROM ... a
    JOIN raw.job_scores s ON ...
    WHERE <untriaged>                       -- no application row for this user
      AND s.fit_score >= %(score_floor)s    -- excludes NULL fit_score too
)
SELECT dedup_hash
FROM scored
ORDER BY power(u, 1.0 / fit_score) DESC      -- A-Res weighted key
LIMIT %(limit)s
```

Notes:

- `fit_score IS NULL` (unscored) is excluded by the `>=` floor — unscored jobs
  never enter the grab bag.
- `seed` is a client-supplied 32-bit int; "New batch" picks a new one.
- This is a **new mode on the existing list endpoint**, not a new table.

### 3.3 What the seed governs (and what it doesn't)

The candidate pool is the **untriaged** set: the moment a job is triaged
(shortlisted / tracked / trashed) it gains an application row and **leaves the
pool**. So the seed is *not* "which 20 jobs forever" — it's the **shuffle order
of whatever is currently in the pool**.

Consequences (worth being precise about, since it's counter-intuitive):

- **Re-running the same seed after triaging a whole batch does NOT replay the
  same 20** — those jobs are gone from the pool. You get the **next 20
  highest-keyed survivors**. Same seed = a stable, repeatable *best-first walk*
  through the pool: triage 20, run again, get the next 20, and so on.
- **An empty screen happens only on pool exhaustion** (< 1 untriaged-above-floor
  job left), never as a side effect of reusing a seed.
- **The seed only changes behavior for *skipped* jobs** — ones you view but don't
  triage. Same seed → they resurface in the same position every batch (you keep
  seeing the cards you've been avoiding). **A new seed reshuffles the
  survivors**, so skipped jobs sink and others bubble up. This is the actual
  reason "New batch" rerolls the seed (not to avoid replaying triaged jobs —
  triage already handles that).

### 3.4 Exhaustion

When the untriaged, above-floor pool is smaller than the batch size, return a
**partial batch** and let the FE render an explicit "you're all caught up" state
once the pool is empty. Fail-loud-not-silent: an empty grab bag is a *rendered
state*, never a blank screen.

## 4. Backend

- **`GET /jobs`** gains `mode` (`table` default | `grabbag`), `seed`, and uses
  the existing `limit`. In `grabbag` mode: ignore `sort`/`page`/`offset`, apply
  the §3.2 query, honor existing `filters` (a user can still constrain the bag),
  default `limit` = the user's `grab_bag_size`, floor = `grab_bag_score_floor`.
  Keep `mode=table` byte-for-byte as today.
- **Settings** — two typed columns on `app.user_search_configs` (migration
  `0016`), following the `0013` alert-thresholds pattern:
  - `grab_bag_size INT NOT NULL DEFAULT 20` (`Field(ge=1, le=50)`)
  - `grab_bag_score_floor INT NOT NULL DEFAULT 3` (`Field(ge=1, le=5)`)
    Add to `SettingsResponse` + a `GrabBagSettingsUpdate`/`Response` pair
    (`extra: "forbid"`).
- **Fail-fast**: validate `mode`/`seed`/floor at the API edge; reject a
  `score_floor` outside 1–5; an empty result is valid (caught-up), not an error.

## 5. Frontend

### Track A — swipe parity

Today the gesture lives in `useRowSwipe.ts` with four hardcoded module-level
constants (`COMMIT_PX=72`, `AXIS_SLOP=8`, `OVERSHOOT_PX=28`,
`OVERSHOOT_RESISTANCE=0.35`) and a `SWIPE_POINTER_TYPES` set. Fine for one table;
the moment it drives four surfaces it needs a central tuning point and an
extension seam for feedback effects. So Track A is **generalize the hook, then
wire it onto cards** — not just wiring.

**1. Central tuning config.** Extract the constants into one typed config with
defaults (`frontend/src/lib/swipe/config.ts`); the hook takes an optional
override merged over defaults:

```ts
export interface SwipeTuning {
  commitPx: number            // travel before release commits ("trigger line")
  axisSlopPx: number          // dead zone: below this a press is a tap, not a swipe
  overshootPx: number         // rubber-band tail past commit
  overshootResistance: number
  pointerTypes: ReadonlySet<PointerType>
}
export const DEFAULT_SWIPE_TUNING: SwipeTuning = { /* current values */ }

useSwipe({ onCommit, tuning })   // tuning?: Partial<SwipeTuning>
```

One file tunes the whole app's feel, with per-surface overrides possible (e.g. a
touchier threshold on grab-bag cards) without forking the hook.

**Two thresholds, named precisely** (they're easy to conflate):

- `axisSlopPx` — the true dead zone; under it nothing moves and a release is a
  plain click (accidental micro-drag stays "un-swiped").
- `commitPx` — the trigger line. The band `[axisSlopPx, commitPx)` is the
  **back-off zone**: the card follows the finger but a release there snaps home
  un-triaged. This recovery already exists (release < commit → snap back);
  centralizing just makes both edges tunable. No separate hysteresis value yet.

**2. Lifecycle edge-callbacks (extension seam).** The hook stays **pure gesture
math + state**; it emits one-shot edge events an effects layer subscribes to —
so animation/haptics/sound drop in later with zero gesture-engine changes:

```ts
useSwipe({ onCommit, onArm, onDisarm, onStart, onSnapBack })
```

The hook already exposes `progress`/`armed`/`settling`/`direction` for
*continuous* visuals (the existing tint ramp; animation stays CSS-driven off
`offset`/`settling`). The new callbacks cover *one-shot* feedback — e.g. a haptic
tick must fire once on `onArm`, not every frame while armed. Effects are
composable add-on hooks that never touch gesture logic and are individually
tree-shakeable / testable:

```ts
useSwipeHaptics(swipe)   // navigator.vibrate on arm/commit — LATER, enabled by this
useSwipeSound(swipe)     // LATER
```

Haptics/sound are **not built in Phase 24** — Phase 24 only lands the callback
API that makes them droppable later.

**3. Rename + relocate.** `useRowSwipe` → `useSwipe`, moved to `lib/swipe/`,
since it's no longer row-specific.

**4. Wire onto the card surfaces.** Map commit-direction → the correct triage
action **per surface** (Jobs: right→shortlist, left→trash; Shortlist / Tracking /
Trash each have their own forward/back semantics — enumerate explicitly, don't
assume symmetry). Reuse the affordance ramp (tint/progress) and click-suppression
(`consumeClickSuppression`) so a swipe doesn't also open the detail panel.

### Track B — grab-bag surface

- New view: a column/grid of `grab_bag_size` swipeable cards from
  `mode=grabbag`. A **"New batch"** control rerolls the seed (and refetches).
- Reuse the card component shape from the existing card surfaces; reuse Track A's
  gesture. Keyboard triage parity (`useTriageKeys`) carries over.
- The "all caught up" empty state (pool exhausted).
- `useJobs` (or a sibling `useGrabBag`) holds the current `seed` in state; reroll
  bumps it. Seed lives in the URL so a batch is shareable/refresh-stable.

### Nav re-rank (cautious, last)

- **Phase the default flip.** Ship the grab bag as a *new tab beside* the table
  first. Once it feels right, flip the default landing route to the grab bag and
  relabel the table view "Search / All jobs." Search is **demoted, not removed.**

## 6. Phasing

Two milestones. **Swipe parity ships first** as its own phase: it's the smallest,
lowest-risk piece (backend-free, one well-abstracted hook), independently
valuable, and a **prerequisite** for the card-based grab-bag surface — so it
de-risks the larger phase and never blocks on gesture plumbing.

### Phase 24 — Swipe parity (Track A, first)

1. **Generalize the swipe hook + parity on cards** — extract a central
   `SwipeTuning` config, add lifecycle edge-callbacks (`onArm`/`onDisarm`/
   `onStart`/`onSnapBack`) as the effects seam, rename `useRowSwipe`→`useSwipe`
   (→ `lib/swipe/`), then wire it onto the card surfaces (Shortlist / Tracking /
   Trash) with per-surface direction mapping enumerated. Haptics/sound are
   *enabled by* this work, not built here. Backend-free. (Spec §5 Track A.)

### Phase 25 — Grab bag (Track B, builds on 24)

1. **Grab-bag backend** — `mode=grabbag` + seeded weighted sampling; `0016`
   settings columns + `GrabBagSettingsUpdate` endpoint + settings UI.
   Deterministic given a seed ⇒ unit-testable. *(Independent of Phase 24 — could
   even start in parallel, but ordered after for focus.)*
1. **Grab-bag surface + "New batch"** — the card view consuming the backend,
   reusing Phase 24's gesture and the caught-up state.
1. **Nav re-rank** — grab bag becomes default landing; table → "Search / All."

## 7. Out of scope / future

- **Persisted deck/session** (server reserves N, tracks seen, draws on empty) —
  deferred; revisit only if stateless reroll proves insufficient.
- **Swipe as eval signal.** Every swipe is a labeled judgment (good / not-good
  against a scored job) — a free stream for `skills_fit` calibration. Argues for
  recording swipe outcomes cleanly, but capturing/using that signal is its own
  eval-forward effort, not this spec.
- **One-card Tinder mode** — rejected for job search (no side-by-side compare).

## 8. Open questions (for ratification)

1. **Score-floor default.** Proposed `3` (decent match and up) on a 1–5 scale.
   `4` is stricter but risks empty bags for users with few high scores; `1`
   defeats the "best matching" intent. Confirm `3`, or pick another.
1. **Default batch size.** Proposed `20`. (User floated 10/20 as examples.)
1. **Nav flip timing.** Proposed: ship beside the table first, flip the default
   in slice 4 once it feels right — *not* flip on day one. Confirm the cautious
   path vs. flipping immediately.

## Changelog

- **2026-06-24** — Initial draft. Forks resolved: weighted-by-fit selection,
  stateless+seed batches, column-of-swipeable-cards UI. Three soft defaults
  (score floor 3, batch size 20, phased nav flip) flagged in §8.
- **2026-06-24** — Added §3.3 clarifying what the seed governs: triage removes
  jobs from the pool, so same-seed reruns walk the pool best-first (never replay
  triaged jobs, never empty-screen except on true exhaustion); the seed only
  affects *skipped* jobs, which is why "New batch" rerolls it. Defaults in §8
  confirmed by user.
- **2026-06-24** — Split phasing into two milestones (§6): Phase 24 = swipe
  parity (first, standalone, backend-free), Phase 25 = grab bag (builds on 24).
- **2026-06-24** — Broadened Phase 24 scope (§5 Track A): central `SwipeTuning`
  config + named thresholds (axis-slop dead zone vs. commit trigger line),
  lifecycle edge-callbacks as the effects seam (haptics/sound droppable later,
  not built now), and `useRowSwipe`→`useSwipe` rename/relocate. Issue #420
  rewritten to match.
