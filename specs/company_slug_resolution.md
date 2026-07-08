# Company name → ATS slug resolution (pipeline-native)

Status: **ratified 2026-07-08.** Issues filed as slices against the phase milestone (§6).
Working notes: `notes/discovery-dorks/README.md`.

## 1. Problem

Users store **raw human company names** in their profile (`app.user_search_configs`,
`companies:` block) — with spaces, slashes, and typos: `blue origin`, `raytheon / rtx`,
`commonwealth fusion systems`. During the overnight run the pipeline consumes those names
**as-is** and feeds them to the ATS scrapers.

Today there is no name→slug resolution step. `config.py` uses the raw name (after naive
normalization) **directly as the ATS board token** (`config.py:353-361`,
`board_token=company`). That works only when a company's real ATS slug happens to equal its
squashed name. When it doesn't, the scrape silently produces nothing:

| Config name                   | Naive key                   | Real slug                 | Result today |
| ----------------------------- | --------------------------- | ------------------------- | ------------ |
| `blue origin`                 | `blueorigin`                | `blueorigin` (lever)      | ✅ lucky     |
| `commonwealth fusion systems` | `commonwealthfusionsystems` | `cfsenergy` (lever)       | ❌ empty     |
| `avalanche energy`            | `avalancheenergy`           | `avalanchefusion` (ashby) | ❌ empty     |
| `relativity space`            | `relativityspace`           | `relativity` (greenhouse) | ❌ empty     |

This is the "silent empty" smell CLAUDE.md warns against: a wrong-but-plausible slug 404s
and we log "not found" instead of "couldn't resolve a slug." The standalone `discover` CLI
(`src/job_scraper/discover.py`) is a manual holdover that only helps if the operator
already knows the slug.

**Goal:** make resolution a first-class, cached, cross-user part of the pipeline so any
human name a user types gets mapped to a verified ATS board — once — and reused forever.

## 2. Current state — what already exists

- **`src/job_scraper/discover.py`** — `probe_company(slug)` hits each ATS endpoint and
  records boards returning 200; `discover_probe`, `run` persist to a flat file. This is a
  reusable **verification** primitive (slug-in → boards-out). Fully mock-HTTP tested
  (`tests/job_scraper/test_discover.py`).
- **`config/company_boards.json`** — flat `{key: [boards]}` map, **baked into the container
  image**, read at scrape time by `config.py:345-375`. The key doubles as the ATS token.
- **`src/pipeline/planner.py`** — reads *every* eligible user's config from `app.*` and
  enqueues per-source work. Already the one place that sees all users' company lists.
- **`src/pipeline/worker.py`** — `default_scrape_fn` writes the per-source payload to temp
  YAML → `config.load_config` → runs scrapers. This is where the flat file is consulted in
  prod.
- **`AnalysisCache`** (`src/agents/remote_filter/cache.py`) — the append-only, composite-key
  cache pattern to mirror for resolution caching.

## 3. Gaps

1. No name→slug step; the raw name is used as the token.
1. Board map is a static flat file, hand-maintained, image-baked — not shared runtime state.
1. Resolution (when done at all) is a separate manual CLI, not part of the run.
1. No persistence/dedup of resolutions across users — the same company typed by two users
   would be resolved (or missed) independently.

## 4. Design

### 4.1 Two tables, both `raw.*` (pipeline-owned)

The pipeline **reads** `app.*` configs and **writes** `raw.*` results — resolution is
derived operational data, not user-authored truth, so it lives in `raw.*` with no API
write-path. (Consistent with CLAUDE.md's `raw.*`/`app.*` boundary: planner already reads
`app.*`; only *writes* are constrained.)

```
raw.company_aliases   -- the cache: normalized human input -> resolution
  normalized_input   text   PRIMARY KEY   -- e.g. "commonwealth fusion systems"
  board              text   NULL          -- 'greenhouse' | 'lever' | 'ashby' | NULL
  slug               text   NULL          -- verified ATS token, or NULL
  status             text   NOT NULL      -- 'resolved' | 'unresolved' | 'needs_review'
  resolver_version   text   NOT NULL      -- bump to invalidate on rule/probe changes
  resolved_at        timestamptz NOT NULL
  -- CHECK: status='resolved' implies board and slug NOT NULL

raw.company_boards    -- verified live boards (canonical identity = the slug)
  board              text   NOT NULL
  slug               text   NOT NULL
  PRIMARY KEY (board, slug)
  last_verified_at   timestamptz NOT NULL
```

`company_aliases` is the "this string points to this ATS slug" cache the whole design hangs
on. `company_boards` is the deduped set of real boards (the canonical identity is the
resolved `(board, slug)` — see §4.4).

### 4.2 Resolution: heuristic-probe primary, search fallback

For a cache-miss input:

1. **Heuristic candidates** — the slug can't be *derived* from the name (there's no formula
   that yields `cfsenergy`), so we generate a few educated guesses and probe them. Default
   rule set, tried in this order (tunable against the golden fixture during impl):

   | #   | Rule                                           | `commonwealth fusion systems` → |
   | --- | ---------------------------------------------- | ------------------------------- |
   | 1   | squash: lowercase + strip all non-alphanumeric | `commonwealthfusionsystems`     |
   | 2   | drop trailing filler word(s), then squash      | `commonwealthfusion`            |
   | 3   | first significant word                         | `commonwealth`                  |
   | 4   | acronym: first letter of each significant word | `cfs`                           |

   Filler list (rule 2): `systems, technologies, technology, inc, corp, corporation, llc, co, company, group, labs, laboratories, aviation, space, energy`. Order matters only for
   probe economy — first 200 wins, so cheap common-case rules (squash) go first.

1. **Probe each candidate** against the three ATS endpoints (reuse `probe_company`). First
   candidate that returns 200 wins. No external dependency; works from Azure datacenter IPs
   (ATS endpoints don't IP-block the way search engines do). Easy majority resolves here:
   `rocket lab`→`rocketlab`, `relativity space`→`relativity`, `spacex`→`spacex`.

1. **Search fallback** — only if every heuristic candidate misses (e.g. `cfsenergy`,
   `avalanchefusion` — un-guessable from the name). One `site:<atsdomain> "<name>"` query
   via **Google Programmable Search (CSE)**, key in `.env` (`GOOGLE_CSE_API_KEY` +
   `GOOGLE_CSE_ID`), non-secret tier/endpoint in YAML per our secrets split. Parse the last
   path segment of the top result as a candidate, then **probe it to verify** before
   trusting. Result is cached forever, so the 100/day free tier is effectively infinite.

1. **Persist**: verified → `resolved` row + `company_boards` upsert; nothing found →
   `unresolved` row (inert — see §4.4); multiple *different* verified slugs → `needs_review`.
   An `unresolved` row is **re-probed after 3 months** (a company may launch a board later);
   until then it's a cache hit that yields no board — no nightly re-probing.

**Verify-before-trust is mandatory:** a heuristic or search candidate is only a *candidate*
until a 200 confirms it. We never cache an unverified guess as `resolved`.

### 4.3 Where it runs: planner-time union pre-pass

Resolution is a **pre-pass in the planner**, before workers run:

1. Gather the **deduped union** of every distinct company name across all eligible users.
1. For each: normalize → look up `company_aliases`. Hit → done (zero network). Miss (or
   `unresolved` past TTL) → resolve (§4.2) → write back.
1. Workers then read resolved slugs from the tables — **no network resolution in the hot
   scrape path.**

Steady state (unchanged user base) = **zero resolution calls per night**. First-ever sighting
of a distinct name = at most a few probes + maybe one cached search call, ever. Five users
who all list "Boeing" → resolved once, not 5×.

### 4.4 Canonical identity = the resolved slug (no fuzzy input matching)

Two different input strings for the same company (`"mongoloid systems"`,
`"mongoloid fighting systems"`) both resolve to the same verified slug `mongoloidsys` and
collapse **at the resolved layer, automatically** — no string-similarity comparison. The
slug is the natural dedup key (same principle as `dedup_hash`).

- **Global, shared alias table.** A verified slug is a fact true for every user; one table,
  no per-user namespacing.
- **Only positive resolutions are load-bearing-shared.** `unresolved`/typo strings get a
  row (so we don't re-probe nightly) but resolve to *nothing* — inert, can't mis-target any
  scrape. So "one user's typo pollutes another" is moot: the shared thing is verified slugs.
- **Ambiguity / collision = fail loud, never auto-pick.** If a single resolution surfaces
  multiple distinct verified slugs (e.g. `rocketlab` vs `rocketlab7`), or a normalized input
  maps to two *different* verified slugs over time, log it and mark `needs_review` — never
  guess or silently overwrite.
- Fuzzy string matching is **out of v1** — at most a future *suggestion* for the
  `unresolved` bucket feeding a human review queue, never a silent auto-merge.

### 4.5 `config.py` consumer change

The `companies` loop (`config.py:345-375`) changes from "key is the token" to a DB lookup:
`normalized_name → company_aliases → (board, slug) → scraper(board_token=slug)`. Behind a
flat-file fallback during migration so nothing breaks if the table is empty.

## 5. Resolved decisions (2026-07-08)

- **`raw.company_boards` + `raw.company_aliases`**, both pipeline-owned in `raw.*`.
- **Heuristic-probe primary; Google Programmable Search (CSE) as cached fallback** — key in
  `.env` (`GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_ID`); 100/day free tier, infinite in practice
  given the cache. (Operator must set up the CSE + key before slice 3 lands.)
- **No Azure-native web search.** Bing Search API retired 2025-08-11; the "Grounding with
  Bing" replacement is an LLM-agent wrapper that hides raw result URLs and costs more —
  wrong tool. **DIY SERP scraping is out** — Google blocks datacenter IPs, and the pipeline
  runs on exactly those. Do not re-litigate.
- **Resolved slug is the canonical identity**; dedup on slug, not input similarity.
- **Global shared alias table**, made safe by verify-before-trust + inert-unresolved +
  fail-loud collision.

## 6. PR slicing (issues filed after ratification)

0. **Migration** — `raw.company_aliases` + `raw.company_boards` tables (Alembic), seeded
   from the current `company_boards.json` (its resolved keys are already real tokens).
1. **Resolver core** — `resolve(name) -> (board, slug, status)`: heuristic candidate
   generation + probe (reuse `probe_company`). Golden name→slug fixture as the red/green
   test (verified pairs below). No search yet.
1. **Alias cache read/write** — `company_aliases` persistence + `company_boards` upsert;
   TTL re-probe for `unresolved`; `needs_review` on collision.
1. **Search fallback** — CSE/Brave client behind the heuristic miss path; verify-before-cache.
1. **Planner pre-pass** — union gather + resolve + persist before enqueue.
1. **`config.py` consumer** — DB lookup with flat-file fallback; then retire the flat file.
1. **Retire/repurpose `discover` CLI** — keep as a manual "re-resolve this name" tool or drop.

**Golden fixture (verified live 2026-07-08):** `commonwealth fusion systems`→`cfsenergy`
(lever), `avalanche energy`→`avalanchefusion` (ashby), `relativity space`→`relativity`,
`rocket lab`→`rocketlab`, `momentus`→`momentus`, `spacex`→`spacex` (greenhouse),
`blue origin`→`blueorigin` (lever). Negative: `boeing`, `lockheed martin` → `unresolved`
(Workday/other, not on a supported board).

## 7. Out of scope

- Fuzzy/typo auto-correction and the human review queue (future; unresolved bucket only).
- ATS boards beyond greenhouse/lever/ashby (Workday/iCIMS/Taleo) — the primes need a
  different scraper entirely, tracked separately.
- Per-user alias namespacing (explicitly rejected — global is the decision).

## 8. Open questions

All prior open questions resolved (2026-07-08):

- **Search backend** → Google CSE, key in `.env` (§4.2 step 3, §5).
- **Heuristic candidate rules** → default ruleset + filler list defined (§4.2 step 1),
  tunable against the golden fixture during impl.
- **Negative-cache TTL** → re-probe `unresolved` after **3 months** (§4.2 step 4).
- **Ambiguity** (search/probe yields multiple distinct slugs, e.g. `rocketlab` vs
  `rocketlab7`) → **`needs_review`, never auto-pick** (§4.4).

Nothing blocking remains; ready to ratify and slice.

## Changelog

- 2026-07-08 — Initial draft. Design converged from `notes/discovery-dorks/`: two `raw.*`
  tables, heuristic-probe primary + cached search fallback, global shared alias table with
  verify-before-trust, slug-as-canonical-identity. All open questions resolved same day:
  Google CSE (key in `.env`) for fallback, default heuristic ruleset + filler list, 3-month
  re-probe TTL for `unresolved`, and `needs_review` (never auto-pick) on ambiguity/collision.
  No blocking questions remain.
  </content>
