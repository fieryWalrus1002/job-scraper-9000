# Prefilter Implementation Plan

_Last updated: 2026-05-16_

This plan turns `specs/prefilter_design.md` into an implementation branch.

## Goal

Add a deterministic routing layer between ingestion and the paid remote filter so raw jobs are split into:

- `data/prefiltered/remote_filter_input.jsonl`
- `data/local/local_jobs.jsonl`
- `data/trash/prefilter_trash.jsonl`

## Branch plan

Suggested branch:

```text
feature/prefilter-router
```

## Deliverables

### New code

```text
src/prefilter/
  __init__.py
  models.py
  router.py
  README.md
```

### New config

```text
config/agent/prefilter.yml
```

### CLI + script

```text
uv run job-scraper prefilter
python scripts/run_prefilter.py
```

### Tests

```text
tests/test_prefilter.py
tests/fixtures/prefilter_cases.jsonl
```

### Docs

```text
specs/prefilter_design.md
specs/prefilter_implementation_plan.md
README.md
project-status.md
```

## Implementation order

### 1. Shared model + annotations

Reuse the existing `JobPosting` input shape and define prefilter annotations.

Add output annotations:

```python
_prefilter_result: Literal["remote_filter_candidate", "local_candidate", "prefilter_reject"]
_prefilter_reason: str
_prefilter_metadata: dict
```

### 2. Deterministic router

Implement a pure routing function that inspects:

- `location`
- `description`
- `title`
- `search_params`

Rules, in order:

1. country gate (`location + description`)
1. local allowlist match
1. obvious onsite/hybrid/local-presence rejects
1. remote-ish / ambiguous → `remote_filter_candidate`

Routing must be single-route only.

### 3. Config loader

Add `config/agent/prefilter.yml` with:

- selected country
- country aliases
- allowlisted local locations
- routing toggles
- weak-signal handling for `search_params`

Keep the config simple and rule-based.

### 4. CLI wiring

Add a `prefilter` subcommand to the existing `job-scraper` CLI.

Requirements:

- default inputs/outputs
- explicit path overrides
- `--dry-run`
- combined input pass over raw records
- one combined output file per bucket

### 5. Script entrypoint

Add `scripts/run_prefilter.py` as a thin wrapper around the same router/CLI logic.

### 6. Tests

Add fixture-based tests for deterministic behavior.

Coverage should include:

- USA vs non-US detection
- country alias normalization
- allowed local matches
- explicit onsite/hybrid outside local area
- missing country fallback
- conflicting `search_params` vs job text
- route exclusivity

## Suggested file responsibilities

### `src/prefilter/router.py`

- pure routing logic
- rule evaluation order
- metadata assembly

### `src/prefilter/models.py`

- output annotation types
- config dataclasses or small helper models

### `src/prefilter/README.md`

- how the router works
- config overview
- CLI usage
- examples of routes

## Acceptance criteria

- `data/raw/` stays untouched as source truth.
- Every input job gets exactly one route.
- Non-US jobs are rejected when the configured country is USA.
- Local allowlisted jobs bypass the remote filter.
- Ambiguous jobs default conservatively to `remote_filter_candidate`.
- CLI and script both work.
- Deterministic fixture tests pass.

## Execution sequence

1. create `src/prefilter/`
1. add config schema + routing rules
1. wire CLI/script
1. add fixtures and tests
1. update docs and project status
1. run targeted tests, then full test suite

## Out of scope for v1

- LLM-based routing
- multi-route fanout
- merging local and remote lanes into skills-fit
- geocoding/radius math
- ambiguity review UI
