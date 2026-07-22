# Remote-filter input sufficiency + gold quality (Phase 34)

**Date:** 2026-07-22
**Status:** RATIFIED (2026-07-22). PR slices may now be filed against Phase 34 (#25).
**Milestone:** Phase 34 (#25).
**Investigation:** `notes/investigations/544-remote-input-sufficiency.md` (#544).
**Related specs:** `remote_filter_taxonomy.md` (LLM = pure extractor, deterministic
`_gate_user`), `remote_filter_classifier_tuning.md`, `remote_filter_eval_decoupling.md`
(gold + categorical metric this builds on), `remote_filter_model_bakeoff.md`.
**Related issues:** #544 (investigation), #509 (the `requires_local_presence` fix — a
subset of this), #492 (flag-level eval — un-deferred here), #97 (closed, root cause).
**Parallel effort:** `scraper_output_contract.md` (Phase 35) — owns the scraper-side
input fixes (typed `search_params`, jobspy `is_remote`/`search_term` signal-drop, HTML
hygiene). Orthogonal: this phase's gold + prompt work does not block on it.

______________________________________________________________________

## Objective

Close the gap between what the remote-filter LLM is fed and what it needs to decide
remote-eligibility, and resolve the onsite-bias prompt tension that lets a bare named
city in the `location` field out-weigh explicit employer remote signals. Eval-forward:
the gold set and metrics land before the prompt change, so the fix is measured, not
vibed.

## Background: what the investigation established

The bake-off framed this as "we feed the model the wrong things." The investigation
(#544) refined that into **three distinct gaps**, only one of which is plumbing:

1. **Prompt-precedence gap (primary).** We already pass `workplace=remote` and the raw
   `location` field into the prompt. The named-city onsite rule
   (`prompts/remote_agent/system_prompt.txt` L17–19, L29) out-weighs the
   `workplace_filter=remote` search context (L12–15) and any remote token in the
   location field. Reproduced across Confluent, Teradata, Stripe, and the DDC family
   (#97/#509). **#509 is the same bug for the `requires_local_presence` flag.**
1. **Location-token hygiene gap.** A `Remote`/`US-Remote`/`Anywhere` token in a
   multi-value `location` field (Stripe: `…; US-Remote; …`) is present in the prompt
   but drowned among cities, with no rule to lift it out as a positive signal.
1. **Body hygiene gap.** 22/106 gold descriptions are fed as **escaped HTML**
   (`&lt;h2&gt;`, `&quot;`, `&#39;`) — classification noise.

Plus gold-quality debt: Confluent already corrected on disk; AppSierra's `remote` label
warrants re-review on its thin 1451-char (likely truncated) body (its copy-pasted note is
a review-app fat-thumb, not provenance rot — the review UI doesn't clear correction fields
between records; papercut → #145); Ringside body self-contradicts; one record has
`company="nan"`.

`workplace=remote` is **supporting, not decisive**: correct on Confluent/Teradata,
**wrong on Whatnot** (`workplace=remote`, body says hybrid, gold=`hybrid`). The design
must not over-correct into "the filter always wins."

## Design

### 1. Signal precedence (the core decision)

Define one explicit precedence order, applied when signals conflict, and rewrite the
prompt around it:

```
explicit in-body policy statement          (highest — "fully remote", "3 days in office", "must reside in X")
  > location-field remote token             ("US-Remote", "Remote", "Anywhere")
  > workplace_filter=remote search context  (employer's own remote filter)
  > bare named city in location field        (lowest — administrative HQ/duty-station)
```

Consequences for the prompt:

- A bare named city **alone** no longer forces `onsite` when a higher remote signal is
  present. Reframe L17–19/L29: "silence is not ambiguity" applies only when **no**
  remote token, remote filter, or in-body remote language exists.
- `requires_local_presence=true` requires an **in-body residence/commute statement**
  ("must reside in / within commuting distance of"), never a `location`-field city
  alone. **This is exactly #509's ask** and is subsumed here.
- An explicit in-body hybrid/onsite statement overrides `workplace_filter=remote`
  (the Whatnot guardrail).

### 2. Location-token surfacing (prompt-build layer)

- In `_build_user_message`, when the `location` field parses to multiple values and one
  is a remote token, emit a dedicated line
  (e.g. `[Location includes an explicit remote option: US-Remote]`) so the signal isn't
  buried among cities. Token set is small and closed; keep it in one place. This is a
  prompt-*presentation* concern, so it stays here.

**HTML hygiene moved out.** The escaped-HTML problem (22/106 gold descriptions) is a
scraper-output issue, not a remote-filter one — it's uniform across all sources because
`scrub()` is PII-only. Ownership moved to `scraper_output_contract.md` (Phase 35 §2),
which cleans `description` at the scrape boundary. Phase 34 keeps only a thin fail-loud
**backstop** on the input contract (defense in depth), not a normalization step.

The location-token change alters prompt text → bumps `prompt_hash`; fold it and the
prompt-precedence change into **one** ratified prompt revision so the cache invalidates
once.

### 3. Eval (lands before the prompt change)

- **Expand the gold set**, teacher-first HITL (`scripts/sample_for_review.py --include-reviewed` → review UI), with three slices:
  - **Location-token remote** (Stripe-type: `US-Remote` among cities, no body remote
    language).
  - **Named-city + soft/absent body language + remote filter** (Teradata/Confluent/DDC
    family — verdict remote).
  - **Filter-says-remote-but-actually-hybrid** (Whatnot-type — verdict hybrid; the
    over-correction guardrail).
- **Un-defer #492:** add flag-level precision/recall/F1 for `requires_local_presence`
  and `requires_relocation`. The categorical metric alone can't see the operative harm
  — `_gate_user` (`src/pipeline/scoring.py`) drops on `requires_local_presence`, so the
  fix must be measured on that flag, not just the 3-way label.
- **Re-review MEDIUM gold candidates with source:** AppSierra (`17f3a913`, thin + bogus
  note), Mistral/Paris (`1b07e146`, `cb17b1f2`), Ringside (`d36d6dcd`, contradictory).
- **Gold repair — normalize 22 stale greenhouse descriptions in place.** 22 records (all
  `greenhouse`: stripe/anthropic/deepmind/figma) were scraped 2026-05-13, before
  `html_to_markdown` (#389, 2026-06-18), so they carry entity-escaped HTML that current
  production would not emit. **Re-fetching is impossible — job postings expire (days to a
  month), the reqs are long gone.** Instead normalize the *stored* text in place with the
  same transform Phase 35 centralizes (`html.unescape` → `html_to_markdown` → `pii.scrub`);
  verified to convert this exact markup cleanly. This makes the gold match live-shape
  input without a re-scrape. Flips `gold_hash` → bake-off re-run. See
  `scraper_output_contract.md` §2.

### 4. Ratify

Score the expanded gold before/after the prompt revision. Ratify only if:

- categorical accuracy non-inferior overall,
- false-onsite / false-`requires_local_presence` rate down on the targeted slice,
- no regression on the Whatnot-type guardrail slice.

Any gold change flips `gold_hash` → re-run all bake-off candidates (the `--bakeoff`
comparable-run guard rejects a mixed-`gold_hash` table).

## Non-goals

- Re-scraping to repair truncated bodies (AppSierra) — track separately if it recurs.
- Fixing HTML at the scraper source — owned by Phase 35 (`scraper_output_contract.md`);
  this phase only repairs the 22 stale gold descriptions in place and keeps a thin
  fail-loud input backstop.
- Changing `_gate_user` semantics — this phase changes extraction quality and its
  measurement, not the deterministic gate.

## PR slices

1. **[#549]** Correct Confluent gold `07209122` onsite→remote — *already applied on
   disk*; remaining work is the bake-off re-run. Fix AppSierra's pasted note when
   re-reviewing it (slice 3).
1. **[#550]** Price `gpt-4.1-mini` in `config/pricing/openai.yml` (independent, trivial).
1. **Gold expansion + re-review** (teacher-first HITL): three new slices above + AppSierra
   note/label re-review + Mistral/Ringside re-review. Flips `gold_hash`.
1. **[#492]** Flag-level `requires_local_presence` / `requires_relocation` eval.
1. **[#509] Prompt revision** (precedence rewrite + location-token surfacing) — one
   prompt bump, measured before/after on the expanded gold. Ratify per §4. (HTML hygiene
   is Phase 35's, not part of this bump.)

Order: 3 and 4 (eval red) before 5 (the fix). 1 and 2 are independent and can land now.

## Changelog

- 2026-07-22 — Initial draft from the #544 investigation.
- 2026-07-22 — Handed the HTML-hygiene item to `scraper_output_contract.md` (Phase 35);
  §2 now covers only location-token surfacing + a fail-loud contract backstop. Noted
  Phase 35 as a parallel, non-blocking effort.
- 2026-07-22 — **RATIFIED.** Added the gold-repair slice (normalize 22 stale greenhouse
  descriptions in place; re-fetch impossible). Corrected the Non-goal + slice 5 that
  still pointed HTML normalization at the prompt boundary — it's Phase 35's.
