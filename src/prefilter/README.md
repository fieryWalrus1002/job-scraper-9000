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
uv run job-scraper-9000 prefilter
python scripts/run_prefilter.py
```

Useful overrides:

```bash
uv run job-scraper-9000 prefilter --input data/raw --dry-run
uv run job-scraper-9000 prefilter --remote-out /tmp/remote.jsonl
```

## Routing rules

1. Reject jobs that mention a non-selected country **and** do not also mention the selected country.
1. Route jobs matching the local allowlist to `local_candidate`.
1. Send everything else to `remote_filter_candidate`.

Onsite/hybrid/must-live-in judgments are intentionally not made here — substring matching on description text produces too many false positives (technical terms like "hybrid-cloud", perks copy like "free onsite gym", wrong-polarity hits like "must live in [the United States]"). Those calls belong to the remote_filter agent, which reads the full JD with context.

## Metadata

Every routed record keeps the original job fields and adds:

- `_prefilter_result`
- `_prefilter_reason`
- `_prefilter_metadata`

The metadata includes config hash, git commit, matched rules, rule trace, and country hits for later debugging.
