"""Human config → the YAML shapes the pipeline already consumes.

Codifies the transform the admin previously did by hand from the intake
templates (specs/configs_in_db_design.md §3). Deterministic: same input,
same output — covered by golden-file tests, plus contract tests that run
``job_scraper.config.load_config()`` over the emitted search config so any
drift against the real parser fails loudly.

Deliberate mapping rules (documented here because they ARE the spec of the
hand-transform):

- Scrape search terms come from target titles only (preferred + exploratory,
  deduped). ``keywords.*`` are scoring/policy inputs, not scrape terms —
  scraping on "finite element analysis" returns noise the prefilter then
  has to discard.
- LinkedIn workplace is the single most-permissive acceptable arrangement
  in the order remote > hybrid > onsite (the LinkedIn scraper takes one
  workplace per search).
- ``cadence`` drives ``linkedin_time`` (daily → day, weekly → week);
  ``freshness_hours`` drives jobspy ``hours_old`` independently — this
  mirrors the admin's hand-maintained config (day + 48h slack).
- jobspy sites are ``linkedin,indeed``: ZipRecruiter is Cloudflare-blocked
  (#12); LinkedIn-via-jobspy supplements the dedicated LinkedIn scraper.
- ``target_companies`` are emitted lowercased into the ``companies:`` block;
  resolution to ATS boards happens via company_boards.json at load time and
  warns loudly on unknown companies (run ``discover`` to register them).
- The SEL section is never emitted — it's an admin-local source the human
  format can't express. The admin's pull keeps it via a local extras merge
  (slice #180's concern).
- The pipeline profile gets ``constraints`` flattened to prefixed strings:
  the skills_fit prompt builder list-joins that field, so a nested
  hard/soft mapping would stringify as a Python dict in the prompt.
"""

from __future__ import annotations

import yaml

from .models import (
    REMOTE_CLASSIFICATIONS,
    CandidateProfileInput,
    Location,
    PrefilterPolicy,
    RemoteClassification,
    RemotePolicy,
    SearchConfigInput,
    UserPolicies,
)

_CADENCE_TO_LINKEDIN_TIME = {"daily": "day", "weekly": "week"}

_COUNTRY_LABELS = {"US": "United States"}


def _dedup(items: list[str]) -> list[str]:
    """Case-insensitive de-dup, first occurrence wins, order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def _titles(search: SearchConfigInput) -> list[str]:
    return _dedup(
        search.roles.target_titles.preferred + search.roles.target_titles.exploratory
    )


def _local_locations(search: SearchConfigInput) -> list[str]:
    locs: list[str] = []
    home = search.user.home_location
    if home is not None:
        locs.append(f"{home.city}, {home.region}")
    for loc in search.locations.acceptable:
        locs.append(_location_label(loc))
    return _dedup(locs)


def _location_label(loc: Location) -> str:
    return f"{loc.city}, {loc.region}"


def _national_location(search: SearchConfigInput) -> str:
    country = search.user.home_location.country if search.user.home_location else "US"
    return _COUNTRY_LABELS.get(country, country)


def _workplace(search: SearchConfigInput) -> str:
    wa = search.work_constraints.work_arrangements
    if wa.remote.acceptable:
        return "remote"
    if wa.hybrid.acceptable:
        return "hybrid"
    return "onsite"  # validator guarantees at least one acceptable


def search_config_to_pipeline_yaml(search: SearchConfigInput) -> dict:
    """Emit the search.yml mapping that job_scraper.config.load_config eats."""
    prefs = search.scrape_preferences
    titles = _titles(search)
    wa = search.work_constraints.work_arrangements

    out: dict = {
        "global": {
            "default_max_results": prefs.max_results_per_task,
            "hours_old": prefs.freshness_hours,
            "linkedin_time": _CADENCE_TO_LINKEDIN_TIME[prefs.cadence],
        }
    }

    if prefs.include_company_board_searches and search.organizations.target_companies:
        out["companies"] = _dedup(
            [c.lower() for c in search.organizations.target_companies]
        )

    if prefs.include_general_job_boards and titles:
        out["linkedin"] = {
            "workplace": _workplace(search),
            "job_type": search.work_constraints.employment_types.acceptable[0],
            "searches": [{"keywords": t} for t in titles],
        }

        jobspy_searches: list[dict] = []
        if prefs.include_remote_national_searches and wa.remote.acceptable:
            national = _national_location(search)
            jobspy_searches += [
                {"search_term": t, "location": national} for t in titles
            ]
        if prefs.include_local_searches:
            for loc in _local_locations(search):
                jobspy_searches += [{"search_term": t, "location": loc} for t in titles]
        if jobspy_searches:
            out["jobspy"] = {
                "sites": "linkedin,indeed",
                "no_remote": not wa.remote.acceptable,
                "searches": jobspy_searches,
            }

    return out


def candidate_profile_to_pipeline_yaml(
    profile: CandidateProfileInput, *, profile_version: str
) -> dict:
    """Emit the candidate_profile.yml mapping skills_fit consumes.

    ``profile_version`` is the authoritative content hash (spec §2), injected
    here so the materialized YAML carries it into run metadata exactly as the
    hand-maintained file did. Any ``profile_version`` in the input is ignored.
    """
    constraints = [f"HARD: {c}" for c in profile.constraints.hard] + [
        f"Soft preference: {c}" for c in profile.constraints.soft
    ]
    return {
        "profile_version": profile_version,
        "summary": profile.summary,
        "level": profile.level,
        "education": list(profile.education),
        "core_skills": list(profile.core_skills),
        "adjacent_skills": list(profile.adjacent_skills),
        "growth_skills": list(profile.growth_skills),
        "preferred_domains": list(profile.preferred_domains),
        "avoided_domains": list(profile.avoided_domains),
        "constraints": constraints,
    }


def derive_policies(search: SearchConfigInput) -> UserPolicies:
    """Per-user policy gates (spec §6) from the search config.

    Acceptable remote classifications follow the work arrangements;
    ``unclear`` is always acceptable — silently dropping unclassifiable
    postings would be a silent filter, and permissive is the default
    posture. Title exclusions merge roles.excluded_titles with
    keywords.excluded.
    """
    classes: set[str] = set()
    wa = search.work_constraints.work_arrangements
    if wa.remote.acceptable:
        # Post-3.0 the agent folds travel into numeric estimated_travel_days,
        # so a remote-with-travel role is classified fully_remote. The legacy
        # remote_with_*_travel buckets are no longer produced and so are not
        # added to new acceptable-sets (specs/remote_filter_simplification.md).
        classes.add("fully_remote")
    if wa.hybrid.acceptable:
        classes.add("hybrid")
    if wa.onsite.acceptable:
        classes |= {"onsite_disguised", "location_restricted"}
    classes.add("unclear")
    # Preserve canonical enum order for stable output.
    ordered: list[RemoteClassification] = [
        c for c in REMOTE_CLASSIFICATIONS if c in classes
    ]

    return UserPolicies(
        remote=RemotePolicy(acceptable_classifications=ordered),
        prefilter=PrefilterPolicy(
            excluded_title_terms=_dedup(
                search.roles.excluded_titles + search.keywords.excluded
            )
        ),
    )


def dump_yaml(data: dict) -> str:
    """Serialize a transform result preserving field order (for run dirs)."""
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=88)
