# Scraper output contract + quality (Phase 35)

**Date:** 2026-07-22
**Status:** RATIFIED (2026-07-22). PR slices may now be filed against Phase 35 (#26).
**Milestone:** Phase 35 (#26).
**Origin:** #544 investigation follow-up (`notes/investigations/544-remote-input-sufficiency.md`).
**Related specs:** `remote_filter_input_sufficiency.md` (Phase 34 — the *consumer* whose
input-sufficiency problems this partly upstreams).
**Related issues:** #14 (post-scrape gate + contract tests — the anchor), #113 (posting
date parsing), #12 (ZipRecruiter Cloudflare 403). New: jobspy signal-drop (this spec).

______________________________________________________________________

## Objective

Make each scraper **accountable for the shape and completeness of what it emits**,
instead of papering over per-source divergence with normalization at each consumer.
The scraper boundary becomes a validated contract that **fails loud** on missing or
misnamed signals — same philosophy CLAUDE.md already applies to `posted_at`
(`JobPosting.__post_init__` normalizes it "at the scraper boundary, so no source
(current or future) can leak a datetime that fails Pydantic validation late").

## Background: what the #544 investigation exposed

`JobPosting.search_params` is a **free-form untyped `dict`** (`models.py:19`). Nothing
enforces field names, so each scraper invented its own:

| Scraper                    | remote signal key                                | keywords key      | job_type   | HTML in description |
| -------------------------- | ------------------------------------------------ | ----------------- | ---------- | ------------------- |
| linkedin                   | `workplace` (canonical)                          | `keywords`        | `job_type` | scrub = PII only    |
| sel (Workday)              | `workplace` (derived) + `source_detail_location` | —                 | `job_type` | scrub = PII only    |
| jobspy (Indeed+ZR)         | **`is_remote`** (bool)                           | **`search_term`** | `job_type` | scrub = PII only    |
| ashby / greenhouse / lever | none (`company`/`board_token` only)              | —                 | —          | scrub = PII only    |
| email_scraper (ZR)         | none                                             | —                 | —          | —                   |

Two concrete failures fall out of the untyped dict:

1. **jobspy silently drops its remote signal and keywords.** The remote-filter input
   contract (`RemoteFilterInput.from_posting`) reads `search_params["workplace"]` and
   `["keywords"]`; jobspy writes `["is_remote"]` and `["search_term"]`; nothing remaps
   them. Every Indeed/ZipRecruiter posting reaches the classifier with its
   employer-declared remote signal thrown away — a silent loss at consumption, exactly
   the anti-pattern CLAUDE.md warns about.
1. **HTML entities reach consumers unscrubbed.** All scrapers call `scrub()` — but
   that's `pii.py` (email/phone redaction), not HTML. 22/106 gold descriptions carry
   `&lt;`/`&gt;`/`&quot;`/`&#39;`. The model (and the review UI) get escaped markup as
   noise.

Neither is a remote-filter bug. Both are the scraper emitting an under-specified,
un-validated payload.

## Design

### 1. Typed search-provenance contract (the accountability fix)

Replace the free-form `search_params: dict` with a validated model — a Pydantic
`SearchProvenance`-shaped contract (or a dataclass with a validating `__post_init__`,
matching the `posted_at` precedent) carrying **canonical** fields:

- `workplace: Literal["remote","hybrid","onsite"] | None`
- `keywords: str | None`
- `job_type: Literal["fulltime","parttime","contract"] | None`
- `source_detail_location: str | None` (Workday-style structured location)
- source-specific opaque fields (e.g. `board_token`, `workday_job_req_id`) allowed but
  segregated, not mixed into the classifier-relevant namespace.

Each scraper is responsible for mapping its native fields into the canonical ones:

- **jobspy:** `is_remote=True → workplace="remote"`; `search_term → keywords`.
- **ashby/greenhouse/lever:** legitimately have no workplace filter (they scrape a
  company's whole board) — they emit `workplace=None` *explicitly*, which is correct and
  now distinguishable from "forgot to set it."
- **linkedin/sel:** already canonical; mechanical.

**Fail-loud:** an unknown/unmapped key that looks classifier-relevant should raise at
the scraper boundary, not pass through. This is the primary guard; the consumer-side
`RemoteFilterInput` keeps a thin validating backstop (defense in depth, same as
CLAUDE.md's "DB constraints are a backstop, not the primary guard").

### 2. Description hygiene at the source

**What already exists (do not re-invent).** HTML→Markdown conversion shipped in **#389**:
`description_formatting.html_to_markdown` (markdownify, ATX headings, `-` bullets,
`escape_misc=False` so the PII scrubber can still see phone punctuation). It is applied
by **greenhouse, ashby, linkedin, lever, sel** — then `pii.scrub` (PII-only) runs. The
frontend renders the result via `react-markdown` (`JobDescriptionSection.tsx`). There is
**no API-side conversion**; cleaning is a scrape-time concern only.

**CONFIRMED live bug — greenhouse descriptions land as raw HTML because the API returns
entity-escaped HTML that defeats `html_to_markdown`.** Root cause pinned against the live
boards API (2026-07-22): `boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true`
returns `content` **entity-escaped** — `&lt;div class=&quot;…&quot;&gt;&lt;p&gt;…`.
`greenhouse.py` *does* call `html_to_markdown`, but markdownify's BeautifulSoup decodes
the entities **once** into literal `<div><p>…` text and never re-parses them as tags, so
raw HTML survives into `description`. (That's why running `html_to_markdown` a *second*
time on a stored description cleans it — the second pass sees real tags.) Verified fix:
`html_to_markdown(html.unescape(content))` → `"SpaceX was founded…"`, clean. **Not a
bypass** — conversion runs; escaped input defeats it. Impact: every greenhouse posting,
every run (1,961 SpaceX in the 2026-07-20 run alone).

Because the fix is a one-liner and the bug is live, it ships as its own small PR
(slice 0 / #551), not gated on the rest of this phase.

The **22 escaped-HTML gold records** are the *same mechanism, older*: scraped 2026-05-13,
before #389 — the old path stored the API's escaped HTML directly. Handled as gold repair
by Phase 34 (normalize in place; re-fetch is impossible, postings expire).

**Second confirmed gap — jobspy skips conversion entirely.** It does
`str(row["description"])` → `scrub`, never calling `html_to_markdown`. Low-risk today
(Indeed/ZR usually return near-plain text) but the same forgot-a-step divergence.

Both gaps are the same root shape: **conversion is per-scraper and easy to skip (jobspy)
or defeat with escaped input (greenhouse).** Centralizing it (below) is the fix.

**Fix = compose the existing pieces into one entry point**, not a new scrubber:

- `clean_description(raw) -> (text, counts)` in `description_formatting.py` — the **only**
  thing scrapers call. Runs `html.unescape` → `html_to_markdown` → `pii.scrub`, in that
  order (unescape first so markdownify sees real tags even on double-encoded input; PII
  last so `escape_misc=False` phone punctuation is still intact for the scrubber — the
  existing #389 rationale).
- **Ship the greenhouse `html.unescape` fix first** as a standalone small PR — that's the
  live production leak, root-caused to the API's entity-escaped `content`. Then route
  *every* scrape path (including jobspy) through `clean_description`, so conversion can't
  be skipped or defeated by construction. Also kills the `linkedin.py` hardcoded
  `{"email": 0, "phone": 0}` default. The accountability win, mirroring §1.

`pii.scrub` keeps its name (it's genuinely PII-only and is fine module-qualified; the
`src/ingest/core.py` `scrub` is unrelated — leave it). This **upstreams** Phase 34 §2's
HTML item — remove it from Phase 34 once this lands.

**`scrub_counts` stays a flat dict — decided, not overlooked.** It *is* load-bearing
(summed for reporting in `_common.py` / `cli.py`, passed through to skills_fit), and by
the letter of the untyped-dict guidance it's a promote-to-typed candidate like
`search_params`. Deliberately **not** typing it this phase — keep churn down; the fix is
additive. Concretely:

- If HTML cleanup emits any counts (e.g. `html_entities_unescaped`), `clean_description`
  adds them into the same flat `scrub_counts` dict, namespaced by prefix so they don't
  collide with `email`/`phone`. (`html_to_markdown` returns no counts today, so this is
  optional — only add keys if the cleanup step actually surfaces a useful number.)
- The reporting sums count **only PII keys** (HTML cleanup is not a redaction). DRY the
  two duplicated `email + phone` summers into one shared helper
  (`pii_redaction_total(scrub_counts)`) so adding a key never silently shifts the metric.

Revisit typing `scrub_counts` only if a third concern lands or a consumer starts
branching on it (per CLAUDE.md's "the moment a field is branched on, promote it").

### 3. Post-scrape quality gate (absorbs #14)

Per-source configurable thresholds enforced right after scrape, failing loud (per
CLAUDE.md "fail fast, log well"):

- minimum job count (catch a source silently returning zero),
- description completeness % (catch truncation — the AppSierra 1451-char case),
- valid `posted_at` rate (relates to #113),
- `workplace`/provenance presence rate per source (catch a future field-name drift like
  the jobspy one before it reaches production).
  Plus contract tests: a captured fixture per scraper asserting the emitted `JobPosting`
  matches the typed contract.

### 4. Adjacent pull-ins (triage, not commitments)

- **#113** posting-date parsing — lives in `dates.py` at the same boundary; natural fit.
- **#12** ZipRecruiter Cloudflare 403 — a source *availability* problem, tangential to
  the *contract*; include only if we're touching the ZR path anyway, else leave standalone.

## Relationship to Phase 34 (parallel, not blocking)

Orthogonal on the eval/prompt axis: Phase 34's gold set is frozen JSONL and its prompt
change weighs signals the model *already* receives, so nothing here blocks it. This
phase improves **production** input quality (and stops the ongoing jobspy signal loss).
The only handoff: Phase 34 §2's HTML item moves here (§2 above); Phase 34 will be amended
to reference this spec as the owner.

## Non-goals

- Cross-source fuzzy dedup (the `compute_hash` comment's deferred idea) — separate.
- Re-scraping historical data to backfill clean shape — forward-only; the gold set is
  corrected via its own HITL path.

## PR slices

0. **[#551] greenhouse raw-HTML fix** — `html.unescape` before `html_to_markdown`.
   Standalone one-liner + regression fixture; the live production leak. Ships first.
1. **Typed `search_params` / provenance contract** + validating boundary (fail-loud) (§1).
1. **Per-scraper mapping to canonical fields** — jobspy `is_remote → workplace`,
   `search_term → keywords` first (the live signal-drop); linkedin/sel already canonical;
   ashby/greenhouse/lever emit `workplace=None` explicitly.
1. **Centralize description hygiene** — `clean_description` = `html.unescape → html_to_markdown → pii.scrub` in `description_formatting.py`; route every scrape path
   (incl. jobspy) through it; drop the `linkedin.py` hardcoded counts default; DRY the
   PII-sum helper. Subsumes #551's fix everywhere. Upstreams Phase 34 §2's HTML item.
1. **Post-scrape quality gate + per-scraper contract tests** (#14).
1. (Optional) #113 date parsing, #12 ZR availability.

Order: slice 0 ships immediately (live leak). Then 1 → 2 (stops the live signal loss),
independently of 3–5.

## Changelog

- 2026-07-22 — Initial draft from the #544 investigation scraper follow-up.
- 2026-07-22 — §2 first draft proposed a new `html_scrub`. **Corrected same day:**
  HTML→markdown already exists (`html_to_markdown`, #389); no new scrubber needed. Then
  **verified against the 2026-07-20 run + live API:** current greenhouse output is *raw
  HTML* at every stage (2,673/2,673). **Root cause pinned:** the boards API returns
  `content` entity-escaped (`&lt;div…`), and markdownify decodes entities once without
  re-parsing, so `html_to_markdown` is *defeated* (not bypassed — it runs). Fix =
  `html.unescape` before `html_to_markdown`, verified against live SpaceX data. Ships as a
  standalone small PR. The 22 escaped-HTML gold records are the same mechanism older
  (pre-#389), repaired in place by Phase 34 (re-fetch impossible — postings expire).
  Broader fix still = centralize `clean_description` + route every path through it.
  `scrub_counts` stays flat.
- 2026-07-22 — **RATIFIED.** Milestone #26 created; greenhouse fix filed as #551 (slice 0).
  Dropped the abandoned `html_scrub`-split framing from the PR slices and the
  `scrub_counts` note (the design is `clean_description` composing the existing pieces).
- 2026-07-22 — Fixed a stale §2 cross-reference: the greenhouse fix is slice 0 / #551
  (was mislabeled "slice 3 / the standalone issue"). Post-merge follow-up to #552.
