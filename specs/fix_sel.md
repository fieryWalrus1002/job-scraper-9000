# Fix SEL Scraper — Workday CXS API

**Status:** scraper loads and runs but returns 0 jobs.

---

## Root cause

The scraper does a `GET` to the Workday listing page HTML and tries to extract a
`data-initial-state` attribute. That attribute does not exist — Workday renders client-side
via React. The HTML shell returned by a plain GET contains no job data at all.

Verified manually:

```
GET https://selinc.wd1.myworkdayjobs.com/en-US/SEL
→ 200, `data-initial-state` not present, no job listings in HTML
```

---

## What actually works

Workday exposes a JSON API under the `wday/cxs/` path. Sending a `POST` with a simple JSON
body returns the full job listing immediately, no browser needed:

```
POST https://selinc.wd1.myworkdayjobs.com/wday/cxs/selinc/SEL/jobs
Content-Type: application/json

{"limit": 20, "offset": 0, "searchText": "", "appliedFacets": {}}

→ 200 {"total": 249, "jobPostings": [...], "facets": [...]}
```

### Response shape (per posting)

```json
{
  "title": "Software Engineer",
  "externalPath": "/job/Pullman-WA/Software-Engineer_JR123",
  "locationsText": "Washington - Pullman",
  "bulletFields": ["2025-16109"]
}
```

`externalPath` is the same field the existing `fetch_description()` code already handles.

### Filtering via `appliedFacets`

Filters are passed as `{"facetParameter": ["id", ...]}`. The IDs match exactly what is
already hardcoded in `SELSearchQuery`:

| Facet parameter   | Descriptor | ID (already in SELSearchQuery) |
|---|---|---|
| `workerSubType`   | Regular    | `96e1096563ef1014e495031ab61a6dff` |
| `workerSubType`   | Temporary  | `96e1096563ef1014e495069e83966e00` |
| `timeType`        | Full Time  | `b0630d66f89e1013409e4b1a1a91c123` |
| `timeType`        | Part Time  | `b0630d66f89e1013409e4ae8d2c9c122` |
| `locationMainGroup` | (unknown, needs investigation) | `df72ee3ddefc1018ebf01de718624e22` |

Note: the location facet parameter is `locationMainGroup`, not `locations` as currently
used in `SELSearchQuery.to_params()`. Need to confirm the GUID maps correctly.

---

## Fix plan

### 1. Add `to_applied_facets()` to `SELSearchQuery`

Replace `to_params()` / `to_url()` with a method that builds the `appliedFacets` dict:

```python
def to_applied_facets(self) -> dict:
    worker_map = {
        "regular": "96e1096563ef1014e495031ab61a6dff",
        "temporary": "96e1096563ef1014e495069e83966e00",
    }
    time_map = {
        "full_time": "b0630d66f89e1013409e4b1a1a91c123",
        "part_time": "b0630d66f89e1013409e4ae8d2c9c122",
    }
    loc_map = {
        "pullman_wa": "df72ee3ddefc1018ebf01de718624e22",
    }

    facets = {}
    worker_ids = [worker_map[s] for s in self.worker_sub_types if s in worker_map]
    if worker_ids:
        facets["workerSubType"] = worker_ids
    time_ids = [time_map[t] for t in self.time_types if t in time_map]
    if time_ids:
        facets["timeType"] = time_ids
    if self.location_key in loc_map:
        facets["locationMainGroup"] = [loc_map[self.location_key]]
    return facets
```

Keep `to_params()` / `to_url()` or delete — they are no longer used by the scraper after
this fix (verify nothing else calls them before removing).

### 2. Rewrite `SELJobScraper.scrape()` to POST with pagination

```python
JOBS_API = "{domain}/wday/cxs/selinc/SEL/jobs"
PAGE_SIZE = 20

def scrape(self) -> list[JobPosting]:
    api_url = f"{self.domain}/wday/cxs/selinc/SEL/jobs"
    headers = {"Content-Type": "application/json"}
    applied_facets = self.query.to_applied_facets()

    all_jobs = []
    offset = 0

    while True:
        payload = {
            "limit": PAGE_SIZE,
            "offset": offset,
            "searchText": "",
            "appliedFacets": applied_facets,
        }
        resp = self.session.post(api_url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        postings = data.get("jobPostings", [])
        if not postings:
            break

        for item in postings:
            # ... same JobPosting construction as now ...

        offset += len(postings)
        if offset >= data.get("total", 0):
            break

    return all_jobs
```

### 3. Update `scraper.base_url` usage

`base_url` is no longer needed for the listing request. Keep it for constructing
`source_url` (prepend domain to `externalPath`) and for `fetch_description()`.

### 4. Verify location GUID

Confirm the `locationMainGroup` GUID `df72ee3ddefc1018ebf01de718624e22` actually filters
to Pullman, WA. Do this by sending:

```python
{"appliedFacets": {"locationMainGroup": ["df72ee3ddefc1018ebf01de718624e22"]}}
```

and checking `locationsText` on returned jobs. If it doesn't filter correctly, check the
`facets` list in the unfiltered response to find the correct ID.

### 5. Update tests

`test_scrape_uses_to_url_not_bare_base_url` and `test_scrape_url_contains_location_guid`
will break because the scraper now POSTs instead of GETs. Replace them with:
- `test_scrape_posts_to_cxs_api_url` — verify `session.post` is called (not `session.get`)
- `test_scrape_passes_applied_facets` — verify the payload contains the expected facets
- `test_scrape_paginates_until_total_reached` — mock two pages and verify both are fetched

The `_mock_session` helper in `test_sel.py` should be updated to mock `session.post`
instead of `session.get`.

---

## Things not to break

- `fetch_description()` still uses a GET to the detail API — leave that alone.
- `_extract_json()` can be deleted once the POST approach is confirmed working.
- `SELSearchQuery` is imported in `config.py` and `cli.py` — keep the class, just add/swap the method.
