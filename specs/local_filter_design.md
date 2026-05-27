# Local Opportunity Filter — Design

**Date:** 2026-05-14

## Problem

The remote filter agent trashes all onsite roles. This is correct for jobs that require physical presence the user cannot meet — but it discards onsite jobs in the user's city that are genuinely reachable. There is no mechanism to recover those.

## Solution

Run jobs through two independent streams before Skills Fit scoring:

```
scraped jobs
    │
    ├─ local filter (regex, no LLM)
    │     match? → local pass → Skills Fit scoring
    │
    └─ remote filter (LLM agent)
          pass?  → remote pass → Skills Fit scoring
          trash? → discard
```

A job reaches Skills Fit scoring if it passes **either** filter. The filters are independent — a job can pass both (a remote role posted with a Pullman address).

______________________________________________________________________

## Local Filter Spec

### Scope

Pure string matching against the job's `location` field. No LLM, no geocoding, no network calls.

### Target cities

Pullman, WA and Moscow, ID — the two cities that make up the Palouse metro area, approximately 8 miles apart.

### Match rules

A job is a **local pass** if its `location` field (case-insensitive) matches any of the following patterns:

| Pattern                  | Rationale                                                       |
| ------------------------ | --------------------------------------------------------------- |
| `pullman`                | Unambiguous city name; state qualifier optional                 |
| `moscow,?\s*(id\|idaho)` | State required — "Moscow" alone is ambiguous (Russia, PA, etc.) |
| `palouse`                | Covers "Palouse, WA" and "Palouse region" references            |

Optionally extend to:

| Pattern                          | Rationale                                 |
| -------------------------------- | ----------------------------------------- |
| `lewiston,?\s*(id\|idaho)`       | Lewiston–Clarkston metro, ~30 miles south |
| `clarkston,?\s*(wa\|washington)` | Twin city to Lewiston                     |

These are off by default — enable via config if commute range is acceptable.

### Implementation

A single function in `src/agents/local_filter/filter.py`:

```python
import re

PATTERNS = [
    re.compile(r"\bpullman\b", re.IGNORECASE),
    re.compile(r"\bmoscow,?\s*(id|idaho)\b", re.IGNORECASE),
    re.compile(r"\bpalouse\b", re.IGNORECASE),
]

def is_local(location: str | None) -> bool:
    if not location:
        return False
    return any(p.search(location) for p in PATTERNS)
```

No config file needed at this stage — patterns are small enough to live in code.

### Pipeline integration

The production runner (`run_remote_filter.py`) and eval driver (`run_remote_filter_eval.py`) both process one job at a time. Local filter runs first, before the LLM call:

```python
if is_local(job.get("location")):
    # route to scoring, skip remote filter
    pass
else:
    # run remote filter as today
```

### Output fields

Local-pass records written to scoring should carry:

```json
{
  "_local_pass": true,
  "_local_match": "pullman"
}
```

This lets the Skills Fit agent and any downstream reporting distinguish local passes from remote passes.

______________________________________________________________________

## Out of Scope

- Geocoding or radius-based matching
- User-configurable city lists (add when there is a second user)
- Integration with the HITL review UI (local passes skip the teacher pipeline entirely — they go straight to scoring)
