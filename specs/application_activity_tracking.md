# Application activity tracking & Upcoming Steps

**Status:** Draft proposal (uncommitted) — 2026-06-17. Open questions resolved
(§10); ready to ratify + assign a milestone. Supersedes the practice of
hand-dating lines into the application `notes` blob.

## 1. Problem

A tracked job's history currently lives as freeform dated lines a user types
into `app.user_applications.notes`:

```
6-17-26: Recruiter heard back, hiring manager is on vacation. No screening yet.
6-11-26: Emailed recruiter@example.com & careers@example.com.
6-2-26:  Referrals added. Waiting on phone screen.
5-30-26: Applied.
5-13-26: Job posted.
```

Two problems:

1. **Manual and tedious** — the user is hand-formatting dates and reverse-chron
   ordering in a textarea.
1. **The data is structurally invisible.** `user_applications` is a single
   *mutable* row: it stores the **current** `status`, one `applied_at` date, and
   `updated_at` (last touch). There is **no history** — we never record *when* a
   job entered `to_apply`, `interview`, etc. Each status change overwrites the
   last. So any time-based question ("how long has this been in To Apply?",
   "days since the interview?") is unanswerable from the DB.

The second point is the crux: the activity log is not just a notes-UX nicety,
it is the **data foundation** required for the Upcoming Steps / alerts feature
the user wants. You cannot derive "3 days in To Apply" without recording when
the state was entered.

## 2. What we track today

- **`raw.job_postings`** — job facts: `dedup_hash`, title, company, location,
  `posted_at`, description, source, `source_url`, `remote_classification`,
  salary…
- **`raw.job_scores`** (per-user) — `fit_score`, `score_rationale`,
  model/provider, `scored_at`…
- **`app.user_applications`** (per user+job) — `dedup_hash` (+ `user_id`),
  `status`, `applied_at` (single date), `notes` (text), `created_at`,
  `updated_at`.

Statuses: `maybe → to_apply → applied → screening → interview → offer → {rejected, hired, ghosted, candidate_withdrew}`, plus `passed` (trash).

## 3. The model

An **append-only event log** alongside the application. `user_applications`
stays the canonical *current* state (status, etc.); events are the *history*.
Status remains denormalized current-state — we do **not** event-source it.

### 3.1 New table — `app.application_events`

| Column        | Type        | Role                                                                                                                            |
| ------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `id`          | uuid pk     |                                                                                                                                 |
| `user_id`     | uuid        | ┐ together reference the application (FK to `app.user_applications`)                                                            |
| `dedup_hash`  | text        | ┘                                                                                                                               |
| `kind`        | text        | discriminator only: `status_change` (typed, auto-emitted) \| `event` (everything else — meaning carried by `tags`); see §3.2.6  |
| `occurred_at` | timestamptz | when it **happened** — user-editable / backdatable (e.g. "5-13-26: posted")                                                     |
| `body`        | text        | the note text                                                                                                                   |
| `tags`        | text[]      | **primary semantic carrier** for non-status events (ECS-style); GIN-indexed + queryable; soft seeded vocab (§3.2.6)             |
| `metadata`    | jsonb       | **inert, display-only** payload (contact email, name, URL) — never queried; load-bearing payload is validated/typed, see §3.2.5 |
| `created_at`  | timestamptz | audit: when the row was inserted                                                                                                |

Index on `(user_id, dedup_hash, occurred_at)`. Composite FK
`(user_id, dedup_hash)` → `user_applications`, `ON DELETE CASCADE` so deleting
an application (untrash that clears the row) removes its events too.

The API models events as a Pydantic **discriminated union on `kind`** with two
arms: `status_change` validates a typed `{from, to}` (the alerts read it); the
generic `event` keeps `metadata` free and carries meaning via `tags` (§3.2.6).
`from`/`to` may later graduate to real columns if the Phase B queries get hot
(see §3.2.5).

### 3.2 Decisions

1. **Status stays on `user_applications`; events are the log.** Not
   event-sourced — deriving current status from events is more machinery than
   this needs.

1. **Every status change auto-emits a `status_change` event** (`occurred_at = now()`, validated `{from, to}` payload — see §3.2.5). The timeline fills in
   Applied / Moved to Interview / … for free, and this is exactly the per-state
   timestamp the alerts need. This is the one place the events log couples to
   the existing triage mutations.

1. **`occurred_at` is the user's truth, `created_at` is the audit.** Manual
   events default `occurred_at` to today but are backdatable; auto-events set it
   to the transition time.

1. **`notes` is kept as a user scratchpad, not migrated.** The freeform `notes`
   field stays as-is — the unstructured margin next to the structured timeline.
   It is *not* retired, and existing dated lines are *not* parsed into events
   (fragile, low-value). Events start fresh.

1. **Strict API boundaries, flexible storage — strictness follows the *data*,
   not the *layer*.** The `metadata` column uses Postgres `jsonb` so events can
   carry varying payload (interview links, contact details) without a migration
   per kind, and the API enforces Pydantic validation on the core envelope
   (`kind`, `occurred_at`, `body`). But "flexible storage" is safe **only for
   inert, display-only fields** — things we render and never aggregate. The
   moment a payload field is **queried, aggregated, or branched on, it is
   load-bearing** and must be validated/typed wherever it lives; unvalidated
   `jsonb` is precisely where schema drift hides and fails silently at
   *consumption* (against FAIL FAST). **Rule: promote a field out of `jsonb` —
   to a validated Pydantic field, and ideally a column — the moment you `WHERE`/
   aggregate/branch on it.** Concretely here, `status_change`'s `{from, to}` is
   load-bearing (Phase B alerts derive "entered To Apply at X" from it), so it
   is **not** a free blob: events are modeled as a Pydantic **discriminated
   union on `kind`** — structured, validated payload for the few kinds that
   carry queried data (`status_change`), a generic `event` (meaning via `tags`,
   §3.2.6) where `metadata` stays free. That is discrimination, not a class-per-type
   hierarchy. If the alert queries get hot, `from`/`to` graduate to real
   columns. DB-level constraints (FK `ON DELETE CASCADE`, a `kind` enum/CHECK,
   `NOT NULL`s) are a cheap **backstop**, not the primary guard — the API is the
   only writer of `app.*` (the pipeline writes only `raw.*`), so Pydantic is the
   schema-of-record.

1. **Tags-first events (ECS-style), with `status_change` as the one structured
   exception.** Following an entity-component intuition, an event's *meaning*
   comes from composable freeform **`tags[]`**, not a rigid `kind` type
   hierarchy — so new event flavors (`contact`, `follow_up`, `interview_prep`,
   …) need **zero migration**, you just attach a tag. `kind` therefore shrinks
   to a 2-value **discriminator** — `status_change` vs. a generic `event` — and
   exists only because of the one hard constraint: `status_change` carries a
   validated, **load-bearing** `{from, to}` payload that the alerts/analytics
   derive timing from, so per the data-boundary rule (CLAUDE.md) it cannot be an
   unvalidated tag/blob. It's the single typed, auto-emitted variant; everything
   else is `kind = 'event'` + tags.

   - **`tags[]` is a real `text[]` column with a GIN index** — queryable
     (`'follow_up' = ANY(tags)`) without the silent-drift trap of `jsonb`. That
     matters because §6's "days since last touch" *does* branch on a tag, so the
     tag must live somewhere queryable, not in inert `metadata`.
   - Where an alert depends on a tag, keep drift down with a **soft, seeded
     vocab** (e.g. `contact`, `follow_up`) — *recommended, not DB-enforced*, so
     the ECS flexibility stays. **Where the seed list lives follows the same
     promotion rule, staged by phase:** in **Phase A** tags are pure user
     organization with no backend consumer, so a **frontend constant** is correct
     (serving it from the API would be plumbing for a consumer that doesn't yet
     exist). Once the **Phase B** rules engine keys off specific tags they become
     load-bearing, so the canonical list moves to **`config/` YAML served to the
     UI** — one source for rule logic *and* suggestions, so they can't drift
     (`follow_up` in a query vs. `followup` in a picker). A tag graduates to a
     typed `kind`/column only if it later earns a hard constraint or a hot query
     (same promotion rule as §3.2.5).

## 4. Backend

- `app.application_events` table + migration.
- CRUD on the application sub-resource:
  - `GET    /api/applications/{dedup_hash}/events` — timeline (desc `occurred_at`)
  - `POST   /api/applications/{dedup_hash}/events` — `{kind, occurred_at?, body, tags?, metadata?}`, validated as a discriminated union on `kind` (§3.2.5)
  - `PATCH  /api/applications/{dedup_hash}/events/{id}`
  - `DELETE /api/applications/{dedup_hash}/events/{id}`
- Status-change endpoints (mark/update) additionally insert a `status_change`
  event in the same transaction.
- All scoped by `user_id` (same auth pattern as the rest of `app.*`).

## 5. Frontend

- **Timeline is Tracking-only.** Shortlist / Jobs / Trash don't get a timeline —
  a job that isn't being actively pursued has no history worth recording, and the
  `application_events` table only has rows once a job reaches Tracking. Keeps the
  surface focused and the write-path scoped to committed applications.
- **Tracking detail panel — Activity timeline.** Reverse-chron list of events,
  each showing date / tags / body. An **"Add note"** button opens a small form:
  date picker (defaults today, backdatable), **tag picker** (seeded suggestions +
  freeform; §3.2.6), text.
- Routes through a `triage(...)`-style mutation hook; React Query invalidation
  on the events query.
- `notes` stays as a freeform scratchpad alongside the timeline (§3.2.4) — the
  timeline is the primary, structured surface; `notes` is the unstructured margin.

## 6. Upcoming Steps / alerts (later, builds on §3–5)

Pure **derivation** over events + timestamps — no new storage, can start
client-side. A small rules engine produces an **Upcoming Steps** pane on the
Tracking page:

- *"You've got 3 jobs at To Apply for over 3 days!"* ← jobs whose latest
  `status_change → to_apply` event is older than the threshold.
- *"It's been 7 days since your interview — time to touch base."* ← latest
  `status_change` with `to = interview` vs. now.
- *"You haven't applied for any jobs in the last X days."* ← max `status_change`
  (`to = applied`) `occurred_at` across all the user's applications.
- *"N application(s) have gone D+ days without a follow-up."* ← jobs whose
  current status is `applied` or `screening` AND whose **last meaningful
  touchpoint** is older than `post_application_nudge_days`. A touchpoint is
  either the status-change event that moved the job into `applied`/`screening`,
  or an `event`-kind row tagged `follow_up` or `contact`. Logging a
  `follow_up`/`contact` event **snoozes** the nudge for that job. This is the
  first rule to consume `event`-kind rows + tags (§3.2.6, "tags as semantic
  carrier").

**Thresholds are config, not hardcoded** — they belong in user settings
(**Phase 18 — Settings & Account**), consistent with the `.env`-secrets /
YAML-config split.

## 7. Phasing

- **Phase A — Activity events:** §3.1 table + §4 CRUD + §3.2.2 status-change
  auto-events + §5 timeline UI. Delivers the note-taking win *and* the data
  foundation.
- **Phase B — Upcoming Steps:** §6 rules engine over the events; thresholds from
  Phase 18 settings. Can begin client-side.

## 8. Downstream features unlocked (future layers)

These are *not* Phase A/B scope — they're recorded to show where the design is
headed and, more usefully, to **stress-test the §3.1 schema**. The takeaway:
**none of them require a change to `application_events`.** They are read-side
derivations or LLM layers on top of the same table, which is the strongest
evidence the foundation is right. All are sequenced after the current
trash→jobs→shortlist focus.

1. **Funnel velocity & drop-off analytics** (read-side; extends Phase B).
   Because every transition is a `status_change` with `occurred_at`, you can
   derive time-in-stage (avg `INTERVAL` between `applied`→`screening`, etc.),
   conversion ratios (`applied`→`screening` vs. straight to
   `rejected`/`ghosted`), and a **global activity feed** — a unified reverse-chron
   crawl of all events across all jobs (the retro-terminal pulse). The per-job
   feed is covered by §4's `GET /{dedup_hash}/events`; the global feed needs one
   **new** cross-job endpoint (`GET /api/events`, user-scoped, desc
   `occurred_at`) — the only additive API surface any of these three imply.

1. **Context-aware follow-up nudge (LLM).** When Upcoming Steps flags a stale
   touchpoint, an "Autodraft follow-up" action compiles the event timeline +
   `raw.job_scores` rationale + contact `metadata` + `notes` and pipes it to a
   local model (`ollama` / a llama.cpp `base_url`) to draft a context-specific
   email. Reads existing data only — no schema change. Contact details ride in
   the inert `metadata` jsonb (read, never `WHERE`d, so it correctly stays a blob
   per §3.2.5).

1. **Layered interview scenario generation (LLM).** A `status_change` to
   `interview` unlocks generating a layered question matrix from the job
   description (core competencies → system constraint → behavioral pivot) to
   "roll" practice scenarios. This is *active prep*, not tracking — it merely
   triggers off the events log; its substance is its own feature and likely
   **warrants its own spec** when the time comes.

1. **Auto-archival rules ("dead-man's switch")** — a Phase-B+ extension where the
   rules engine stops merely *surfacing* an alert and *writes back*: e.g. a job in
   `screening`/`interview` with no `contact`/`follow_up` event for N days
   auto-fires a `status_change → ghosted`. Composes cleanly — it's just a
   programmatic status change, so §3.2.2 emits the timeline entry recording when
   and why it archived. **Design fork worth flagging:** Phase B (§6) is *read-only
   derivation*; an auto-mutating rule is a deliberate step past that, so it must be
   **config-gated** (threshold in Phase 18 settings, off by default) and trivially
   reversible (normal triage un-ghosts it). Note it; don't let write-back creep
   into the Phase B engine silently.

1. **Local-first exhaust** (small, independent, no schema change):

   - **Flat Markdown archival** — on a terminal state
     (`rejected`/`hired`/`ghosted`/`candidate_withdrew`), a route compiles
     `raw.job_postings` + `raw.job_scores` rationale + the full event timeline into
     one Markdown file with flat YAML frontmatter (facts + `tags`) for an
     Obsidian-style vault — no nested folders, discovery via tags/metadata.
     Reinforces tags-as-semantic-carrier (§3.2.6).
   - **Local webhook broadcasts** — instead of the (out-of-scope) email/push
     digests, fire a JSON payload to a configured local URL when the engine raises
     an alert or a notable `status_change` lands, for a home-automation hub (Home
     Assistant, Zigbee lights). The URL is non-secret → `config/` YAML, not `.env`.
     Lightweight; no notification service to run.

> **Eval-forward applies to the LLM layers.** The core Activity-events feature
> (§3–6) is plain CRUD + a rules function — no agent, so the eval-forward rule
> doesn't apply. Layers 2 and 3 *are* LLM features and **are** subject to it
> (eval harness before production runner).

## 9. Out of scope / future

- Event-sourcing the status (rejected, see §3.2.1).
- One-time parse/import of existing `notes` lines into events (§3.2.4).
- Email/push digests of Upcoming Steps (the pane is in-app first).
- LLM assists (timeline summary, follow-up nudge, interview-prep generation) —
  see §8; future layers, not required for Phase A/B. The core feature here is
  plain CRUD + a rules function.

## 10. Open questions

All resolved as of this revision (ready to ratify):

- **`notes` retired or kept?** → **Kept** as a freeform scratchpad alongside the
  timeline (§3.2.4, §5).
- **`kind` vocabulary — enum vs. tags vs. both?** → **Tags-first**: meaning rides
  on freeform `tags[]`; `kind` is just a `status_change` vs. `event` discriminator
  (§3.2.6).
- **Timeline on non-Tracking surfaces?** → **No, Tracking-only** (§5).

## 11. Phase 23 — Notes deprecation & latest-activity column

The activity timeline (§3–5) has fully superseded the legacy free-text
`app.user_applications.notes` field. Phase 23 retires `notes` and reclaims its
Tracking-table column to show each job's most recent activity at a glance.

**This reverses two earlier decisions:** §10 ("`notes` kept as a freeform
scratchpad") and §9 ("one-time parse/import of existing `notes` into events" —
out of scope). Both are now superseded — `notes` is migrated into events and
dropped.

### 11.1 Latest activity on the list

- `GET /applications` gains an optional `latest_event` field on the `Application`
  out-model: the single most recent `application_events` row for that job by
  `occurred_at` (lateral join, `LIMIT 1`). Shape carries enough to render
  compactly — `kind`, `occurred_at`, and either the resolved status label
  (`status_change`) or the note `body` (`event`). `None` when a job has no events.
- Backfilled note events (§11.3) are picked up by this join automatically, so a
  migrated note shows as the latest activity if it's the most recent row.

### 11.2 Tracking-table column

- The **Notes** column becomes **Latest activity**, rendering `latest_event`:
  a `status_change` shows the compact label ("Entered Applied"), an `event` shows
  its truncated body, both with a relative timestamp ("· 3d ago"). No events → em-dash.
- The table stops reading `app.notes` (removed in 11.3).

### 11.3 Notes migration & removal

- Migration `0015`: for each `user_applications` row with non-empty `notes`,
  insert a `note` event (`kind='event'`, `body = notes`, no tags) carrying that
  text, then `DROP COLUMN notes`. No data loss; existing notes become first-class
  timeline events.
- `notes` is removed from the API model, create/update bodies, and the list query.
- The notes textarea is removed from `ApplicationTrackingSection` (the timeline +
  add-note form is now the only way to record narrative).

### 11.4 Slicing

1. `fix(timeline)` — status-change row overlap + sibling rendering sweep (standalone).
1. `feat(api)` — `latest_event` on the applications list (additive; no notes code).
1. `feat(tracking)` — "Latest activity" column; stop reading `app.notes` (needs #2).
1. `refactor(notes)` — migration `0015` (backfill + drop) + remove `notes` from
   API/UI (needs #3, drops the column last after nothing reads it).

## Changelog

- **2026-06-24** — §11: Phase 23 — deprecate legacy `notes` (migrate to `note`
  events via migration `0015`, drop the column) and repurpose the Tracking
  **Notes** column as **Latest activity** (new `latest_event` on the applications
  list). Reverses the §10 "notes kept" and §9 "notes import out of scope" decisions.
- **2026-06-24** — §6: Added 4th alert rule `post_application` (touchpoint-aware
  post-application follow-up nudge). Consumes `event`-kind rows with `follow_up`/
  `contact` tags as snooze signals. Threshold `post_application_nudge_days` from
  user settings (default 10 days).
