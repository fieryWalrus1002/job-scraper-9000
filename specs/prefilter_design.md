# Prefilter Design

_Last updated: 2026-05-16_

This spec defines a deterministic routing layer that sits between raw scraping and the paid remote-filter LLM. It is intentionally **not** an agent and does **not** use an LLM.

## Goals

- Reduce paid remote-filter calls by routing obvious jobs cheaply.
- Preserve `data/raw/` as the immutable source truth.
- Separate local jobs from remote-filter candidates without losing provenance.
- Reject obvious non-US jobs early when the configured country is USA.
- Keep the router simple, deterministic, and easy to test.

## Non-goals

- No semantic remote-policy reasoning.
- No LLM calls.
- No multi-route fanout per job.
- No merge into skills-fit yet.

## Proposed placement

```text
src/prefilter/
  __init__.py
  models.py
  router.py
  README.md

config/agent/prefilter.yml
scripts/run_prefilter.py
```

CLI entrypoints:

```bash
uv run job-scraper prefilter
python scripts/run_prefilter.py
```

## Data flow

```text
data/raw/*.jsonl
  ↓
prefilter router
  ├─ data/prefiltered/remote_filter_input.jsonl
  ├─ data/local/local_jobs.jsonl
  └─ data/trash/prefilter_trash.jsonl
```

`data/raw/` remains source truth. The router consumes the combined raw set and writes one combined output file per bucket.

## Inputs

The router reuses the existing `JobPosting` shape as input.

Primary signals:

- `location`
- `description`
- `title`
- `search_params`

Weak signal:

- `search_params.location`

Important provenance fields already present on `JobPosting`:

- `dedup_hash`
- `scraped_at`
- `source`
- `source_url`

## Outputs

Each routed record preserves the original job fields and adds annotations.

Required annotations:

```python
_prefilter_result: Literal["remote_filter_candidate", "local_candidate", "prefilter_reject"]
_prefilter_reason: str
_prefilter_metadata: dict
```

Recommended metadata fields:

- `schema_version`
- `config_hash`
- `commit`
- `selected_country`
- `matched_rules`
- `rule_trace`
- `routing_decision_source`
- `local_policy_version`

Example:

```json
{
  "_prefilter_result": "local_candidate",
  "_prefilter_reason": "allowed_local_location",
  "_prefilter_metadata": {
    "schema_version": "1.0.0",
    "config_hash": "...",
    "commit": "...",
    "selected_country": "USA",
    "matched_rules": ["local_area_allowlist"],
    "rule_trace": ["country_check:pass", "local_location_check:pass"],
    "routing_decision_source": "location"
  }
}
```

## Routing rules

The router is deterministic and single-route only.

### 1. Country gate

First check whether the job is in the configured country.

- Configured country is explicit, e.g. `USA`
- Country detection uses `location + description`
- A small alias map is allowed (`US`, `U.S.`, `United States`, etc.)
- Missing or ambiguous country does **not** auto-reject
- Explicit non-US country is a hard reject

If explicit non-US country is detected:

```text
prefilter_reject
```

### 2. Local allowlist

If the job explicitly matches an allowed local location, route it as:

```text
local_candidate
```

This is based on explicit allowlisted locations only in v1.

### 3. Remote-ish / ambiguous jobs

If the job is not clearly local and not clearly non-viable, route it to:

```text
remote_filter_candidate
```

This bucket feeds the paid remote-filter LLM.

### 4. Obvious rejects

Reject jobs that clearly violate routing policy, such as:

- explicit onsite outside the allowed local area
- explicit hybrid outside the allowed local area
- relocation required
- local presence required
- explicit non-US country

## Precedence

If signals conflict:

1. explicit job text wins
2. location beats description when both are present
3. search params are weak tie-breakers only
4. job text beats search intent

## Config

`config/agent/prefilter.yml` is the policy source of truth.

Suggested shape:

```yaml
country: USA

country_detection:
  enabled: true
  sources: [location, description]
  aliases:
    USA: ["US", "U.S.", "United States", "United States of America", "America"]
  unknown_policy: continue

local_area:
  allowed_locations:
    - "Pullman, WA"
    - "Seattle, WA"

routing:
  route_local_jobs: true
  route_remote_candidates: true
  reject_non_us: true
  prefer_search_params_as_weak_signal: true
```

The config should be easy to tune later without changing code.

## CLI contract

Default behavior:

```bash
uv run job-scraper prefilter
```

Script fallback:

```bash
python scripts/run_prefilter.py
```

Recommended flags:

- `--input`
- `--config`
- `--remote-out`
- `--local-out`
- `--trash-out`
- `--dry-run`

Defaults should support the common case, with overrides for tests and backfills.

## Test strategy

Because routing is deterministic, ambiguity should be covered with fixture-based tests.

Recommended fixture location:

```text
tests/fixtures/prefilter_cases.jsonl
```

Fixture coverage should include:

- explicit USA jobs
- explicit non-US jobs
- allowed local matches
- explicit onsite outside local area
- hybrid outside local area
- missing country
- alias normalization
- conflicting `search_params` vs job text
- ambiguous remote wording

## Integration with the rest of the pipeline

### Upstream

Scrapers continue writing normalized records to `data/raw/`.

### Downstream

- `remote_filter_candidate` → remote-filter LLM
- `local_candidate` → future local lane
- `prefilter_reject` → trash

The prefilter does not merge local and remote lanes yet; that is deferred to later phases.

## Open implementation questions

- Should the router be pure library + CLI, or expose a small public API for reuse?
- Should config hashing include the resolved env-expanded YAML only, or also supporting code version?
- Should `local_candidate` records keep a distinct output schema later, or remain the same JobPosting shape with annotations?
