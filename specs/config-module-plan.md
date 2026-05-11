# Config Module Plan

## Goal

Parse a YAML search config into a flat `list[BaseScraper]` — one entry per search — so the pipeline can call `.scrape()` on each without knowing where it came from or how it was configured.

---

## New files

| Path | Purpose |
| --- | --- |
| `src/job_scraper/config.py` | YAML loader, config dataclasses, scraper builder |
| `tests/test_config.py` | Unit tests for parsing, override resolution, builder output |
| `example-search-config.yml` | Reference config (already exists) |

## New dependency

`pyyaml` — add via `uv add pyyaml`.

---

## Config structure (mirroring the YAML)

Three internal dataclasses, none of which are exposed publicly — they're only used to carry parsed state through the builder:

```python
@dataclass
class _GlobalDefaults:
    default_max_results: int = 50
    hours_old: int = 24
    linkedin_time: str = "day"       # maps to TIME_MAP keys
    salary_floor_k: int | None = None

@dataclass
class _LinkedInSection:
    experience: str = "2,3,4,5"
    workplace: str = "remote"
    job_type: str = "fulltime"
    searches: list[dict] = field(default_factory=list)

@dataclass
class _JobSpySection:
    sites: str = "linkedin,indeed,zip_recruiter"
    no_remote: bool = False
    searches: list[dict] = field(default_factory=list)

@dataclass
class _GreenhouseSection:
    boards: list[str] = field(default_factory=list)
```

Note: the top-level YAML key is `global` (a Python reserved word). Read it as a plain dict key — `raw["global"]` — and immediately map it to `_GlobalDefaults`.

---

## Public API

```python
def load_config(path: str | Path) -> list[BaseScraper]:
    ...
```

Takes a path to a YAML file, returns a flat list of fully configured `BaseScraper` instances ready to call `.scrape()` on. Raises `ConfigError` (a custom exception subclassing `ValueError`) on any validation failure.

---

## Override precedence (low → high)

```
scraper class defaults
    ↓
global section
    ↓
scraper section (linkedin / jobspy)
    ↓
per-search entry overrides
```

Per-search entries in the YAML can override any field that makes sense to vary per search. For the initial implementation, the supported per-search overrides are:

| Scraper | Per-search overrides |
| --- | --- |
| `linkedin` | `keywords` (required), `salary_floor_k`, `time`, `experience`, `workplace` |
| `jobspy` | `search_term` (required), `location`, `hours_old`, `sites` |
| `greenhouse` | n/a — boards are a flat list, no per-board overrides |

---

## Builder logic

### `_build_linkedin(section, globals) -> list[LinkedInJobScraper]`

For each entry in `section.searches`:
1. Merge: scraper-section fields, then per-search overrides
2. Construct `LinkedInSearchQuery` using `_TIME_MAP`, `_WORKPLACE_MAP`, `_JOBTYPE_MAP` (same maps as `cli.py` — either import them or move them to a shared `_maps.py`)
3. Return `LinkedInJobScraper(query)`

### `_build_jobspy(section, globals) -> list[JobSpyScraper]`

For each entry in `section.searches`:
1. Merge: section fields, then per-search overrides
2. `location` defaults to `"USA"` if not specified in the per-search entry
3. Construct `JobSpyQuery`
4. Return `JobSpyScraper(query)`

### `_build_greenhouse(section) -> list[GreenhouseScraper]`

For each token in `section.boards`:
1. Construct `GreenhouseQuery(board_token=token, fetch_descriptions=True)`
2. Return `GreenhouseScraper(query)`

No global overrides apply to Greenhouse — there are no configurable parameters.

---

## CLI integration

Add a `run-config` subcommand to `cli.py`:

```bash
uv run job-scraper run-config example-search-config.yml --save
uv run job-scraper run-config example-search-config.yml --dry-run
```

The `run-config` command:
1. Calls `load_config(path)` to get `list[BaseScraper]`
2. Logs a summary of what's about to run (count per scraper type)
3. Iterates the list, calls `.scrape()` on each, accumulates `list[JobPosting]`
4. Writes output via `_output()` / `_resolve_dest()` (same helpers already in `cli.py`)

### `--dry-run` flag

Print what would be scraped without making any network calls. For each scraper in the list, print:
- scraper type and `source_name`
- key query parameters (keywords, time, salary floor, sites, board token)

This is useful for validating a config before scheduling it.

---

## Validation (at parse time, before any scraping starts)

Raise `ConfigError` early on:

- A LinkedIn search entry is missing `keywords`
- A JobSpy search entry is missing `search_term`
- `linkedin_time` is not one of `day | week | month | any`
- `workplace` is not one of `remote | onsite | hybrid`
- `job_type` is not one of `fulltime | parttime | contract`
- `salary_floor_k` is not one of the valid LinkedIn values (`40, 60, 80, 100, 120`) if provided
- `sites` contains an unrecognised site name (validate against `JOBSPY_SITES` in `scrapers/jobspy.py`)
- All three scraper sections are absent (nothing to do)

Unknown keys in per-search entries should log a warning and be ignored, not raise — keeps the config forward-compatible.

---

## Shared maps

`_TIME_MAP`, `_WORKPLACE_MAP`, `_JOBTYPE_MAP` are currently private to `cli.py`. The config module needs them too. Two options:

- **Option A** — Move them to a new `src/job_scraper/_maps.py` and import from both `cli.py` and `config.py`. Clean, no duplication.
- **Option B** — Inline them in `config.py` (duplication, but both files stay self-contained).

**Recommendation: Option A.** The maps are already meaningful shared constants, not CLI-specific logic.

---

## Tests to write (`tests/test_config.py`)

### Parsing
- Valid full config parses without error
- Missing `global` section uses all defaults
- Missing `linkedin` / `jobspy` / `greenhouse` sections are skipped (no scrapers built for them)
- All-absent sections raise `ConfigError`

### Override precedence
- Global `salary_floor_k` flows into LinkedIn queries
- Global `linkedin_time` flows into LinkedIn queries
- Per-search `salary_floor_k` overrides the global value
- Per-search `location` on a jobspy entry overrides the `"USA"` default
- Section-level `experience` overrides the query default

### Builder output
- LinkedIn section with 3 searches produces 3 `LinkedInJobScraper` instances
- JobSpy section with 2 searches produces 2 `JobSpyScraper` instances
- Greenhouse with 4 boards produces 4 `GreenhouseScraper` instances
- Total count of scrapers matches sum of searches + boards

### Validation errors
- LinkedIn search missing `keywords` raises `ConfigError`
- JobSpy search missing `search_term` raises `ConfigError`
- Invalid `linkedin_time` value raises `ConfigError`
- Invalid `salary_floor_k` value raises `ConfigError`

### Dry-run (once CLI subcommand is wired)
- `--dry-run` exits 0 and prints scraper list without calling `.scrape()`

---

## Cron usage (after implementation)

```cron
0 7 * * * cd /path/to/job-scraper-9000 && uv run job-scraper run-config search-config.yml --save >> /var/log/job-scraper.log 2>&1
```

A single cron entry runs all searches across all scrapers defined in the config. Output files land in `data/raw/` with auto-generated names per scraper run, named by date + source + keywords as before.

---

## Open questions

1. **Merge vs. replace for `sites` per-search override on jobspy** — if a search entry specifies `sites: linkedin`, does that replace the section-level `sites` or union with it? Recommendation: replace (most explicit wins).

2. **Single output file vs. one file per scraper** — currently `--save` writes one file per CLI invocation. With `run-config`, should all results land in one file (e.g. `2026-05-11_config-run.jsonl`) or one per scraper? One-per-scraper is consistent with the existing naming scheme and makes it easier to debug which source produced what. Recommendation: one file per scraper, same as today.

3. **Failure isolation** — if one scraper raises an exception mid-run (e.g. LinkedIn rate-limits), should the whole run abort or should remaining scrapers still execute? Recommendation: catch per-scraper exceptions, log them, continue. A failed scraper produces 0 results and a log entry; it doesn't kill the run.

4. **Config reload at cron time** — the config is read fresh on each invocation since the process exits after each run. No caching concern.
