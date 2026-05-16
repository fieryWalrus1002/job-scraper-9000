# Prefilter Router

A deterministic routing layer that splits raw scraped jobs into local, remote-filter, and reject buckets.

## Why it exists

The raw scrape output is immutable source truth. The prefilter simply decides what should:

- bypass the paid remote filter and stay in a local lane
- proceed to the remote filter for semantic remote-policy review
- be rejected early because it is clearly non-viable or non-US

## Inputs

- `data/raw/*.jsonl`
- `config/agent/prefilter.yml`

## Outputs

- `data/prefiltered/remote_filter_input.jsonl`
- `data/local/local_jobs.jsonl`
- `data/trash/prefilter_trash.jsonl`

## CLI

```bash
uv run job-scraper prefilter
python scripts/run_prefilter.py
```

Useful overrides:

```bash
uv run job-scraper prefilter --input data/raw --dry-run
uv run job-scraper prefilter --remote-out /tmp/remote.jsonl
```

## Routing rules

1. Reject jobs with explicit non-selected-country signals.
2. Route jobs matching the local allowlist to `local_candidate`.
3. Reject obvious onsite/hybrid/local-presence jobs outside the local area.
4. Send everything else to `remote_filter_candidate`.

## Metadata

Every routed record keeps the original job fields and adds:

- `_prefilter_result`
- `_prefilter_reason`
- `_prefilter_metadata`

The metadata includes config hash, git commit, matched rules, rule trace, and country hits for later debugging.
