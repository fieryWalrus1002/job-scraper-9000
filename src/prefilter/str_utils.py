import re
from typing import Any
from .models import PrefilterConfig, DEFAULT_COUNTRY_ALIASES


######################### Helper functions we keep internal ################################

# US state abbreviation → full name. Used by _location_contains so that an
# allowed_location like "Pullman, WA" matches a posting location like
# "Washington - Pullman" (and vice versa). Scoped to location matching only —
# do not apply during _contains_phrase, where canonicalizing "or" → "oregon"
# would corrupt reject/remote hint matching on natural-language descriptions.
_STATE_ABBREVIATIONS: dict[str, str] = {
    "al": "alabama",
    "ak": "alaska",
    "az": "arizona",
    "ar": "arkansas",
    "ca": "california",
    "co": "colorado",
    "ct": "connecticut",
    "de": "delaware",
    "fl": "florida",
    "ga": "georgia",
    "hi": "hawaii",
    "id": "idaho",
    "il": "illinois",
    "in": "indiana",
    "ia": "iowa",
    "ks": "kansas",
    "ky": "kentucky",
    "la": "louisiana",
    "me": "maine",
    "md": "maryland",
    "ma": "massachusetts",
    "mi": "michigan",
    "mn": "minnesota",
    "ms": "mississippi",
    "mo": "missouri",
    "mt": "montana",
    "ne": "nebraska",
    "nv": "nevada",
    "nh": "new hampshire",
    "nj": "new jersey",
    "nm": "new mexico",
    "ny": "new york",
    "nc": "north carolina",
    "nd": "north dakota",
    "oh": "ohio",
    "ok": "oklahoma",
    "or": "oregon",
    "pa": "pennsylvania",
    "ri": "rhode island",
    "sc": "south carolina",
    "sd": "south dakota",
    "tn": "tennessee",
    "tx": "texas",
    "ut": "utah",
    "vt": "vermont",
    "va": "virginia",
    "wa": "washington",
    "wv": "west virginia",
    "wi": "wisconsin",
    "wy": "wyoming",
    "dc": "district of columbia",
}


def _tokens(text: str | None) -> list[str]:
    norm = _normalize_text(text)
    return norm.split() if norm else []


def _phrase_tokens(phrase: str) -> list[str]:
    return _tokens(phrase)


def _contains_phrase(text: str | None, phrase: str) -> bool:
    haystack = _tokens(text)
    needle = _phrase_tokens(phrase)
    if not haystack or not needle:
        return False
    if len(needle) == 1:
        return needle[0] in haystack
    limit = len(haystack) - len(needle) + 1
    for idx in range(max(limit, 0)):
        if haystack[idx : idx + len(needle)] == needle:
            return True
    return False


def merge_country_aliases(
    selected_country: str,
    configured_aliases: dict[str, list[str]],
) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {
        country: list(aliases) for country, aliases in DEFAULT_COUNTRY_ALIASES.items()
    }
    for country, aliases in configured_aliases.items():
        merged.setdefault(country, [])
        for alias in aliases:
            if alias not in merged[country]:
                merged[country].append(alias)
    merged.setdefault(selected_country, [])
    if selected_country not in merged[selected_country]:
        merged[selected_country].append(selected_country)
    return merged


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _canonicalize_state_tokens(tokens: list[str]) -> list[str]:
    return [_STATE_ABBREVIATIONS.get(t, t) for t in tokens]


def _location_contains(text: str | None, allowed_location: str) -> bool:
    """Match an allowed_location against text with US state-abbreviation
    canonicalization and set containment.

    Fixes the case where 'Pullman, WA' (config) should match 'Washington -
    Pullman' (posting) even though they share no contiguous token sequence:
    canonicalizing both sides yields {pullman, washington}, then subset.
    """
    needle = _canonicalize_state_tokens(_phrase_tokens(allowed_location))
    haystack = _canonicalize_state_tokens(_tokens(text))
    if not needle or not haystack:
        return False
    return set(needle).issubset(haystack)


def _flatten_strings(value: Any) -> list[str]:
    out: list[str] = []
    if value is None:
        return out
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        for item in value.values():
            out.extend(_flatten_strings(item))
        return out
    if isinstance(value, (list, tuple, set)):
        for item in value:
            out.extend(_flatten_strings(item))
        return out
    return [str(value)]


def _country_hits(
    texts: list[str],
    aliases: dict[str, list[str]],
    selected_country: str,
) -> tuple[list[str], dict[str, str], str | None]:
    hits: list[str] = []
    alias_hits: dict[str, str] = {}
    hit_source: str | None = None
    for source_idx, text in enumerate(texts):
        if not text:
            continue
        for country, country_aliases in aliases.items():
            if country in hits:
                continue
            for alias in country_aliases:
                if _contains_phrase(text, alias):
                    hits.append(country)
                    alias_hits[country] = alias
                    if hit_source is None:
                        hit_source = (
                            ["location", "description", "title", "search_params"][
                                source_idx
                            ]
                            if source_idx < 4
                            else "unknown"
                        )
                    break
    # Keep selected country first if it exists
    if selected_country in hits:
        hits = [selected_country] + [c for c in hits if c != selected_country]
    return hits, alias_hits, hit_source


def _local_match(
    job: dict[str, Any],
    cfg: PrefilterConfig,
    *,
    flat_search_params: list[str],
) -> tuple[bool, str | None]:
    location = str(job.get("location") or "")
    description = str(job.get("description") or "")
    allowed = [x for x in cfg.local_area.allowed_locations if x]
    if cfg.local_area.home_location:
        allowed.append(cfg.local_area.home_location)

    for allowed_location in allowed:
        if _location_contains(location, allowed_location):
            return True, "location"
        if _location_contains(description, allowed_location):
            return True, "description"
        if cfg.routing.prefer_search_params_as_weak_signal:
            for value in flat_search_params:
                if _location_contains(value, allowed_location):
                    return True, "search_params"
    return False, None


def _has_phrase(texts: list[str], phrases: list[str]) -> tuple[bool, str | None]:
    for text in texts:
        for phrase in phrases:
            if _contains_phrase(text, phrase):
                return True, phrase
    return False, None


############### functions we call in router.py ###########################33


def check_banned_terms(
    company: str, title: str, location: str, description: str, banned_terms: dict
) -> tuple[bool, str | None]:
    """
    Helper function to check if any of the banned terms are present in the texts. Returns a tuple of (is_banned, matched_term).

    e.g:
    banned_terms = {
        "ai_factory": ["upwork", "freelancer", "fiverr"],
        "other_category": ["some other term"],
    }

    If a job's title/location/description/search_params contains "upwork", this would return (True, "ai_factory:upwork"),
    which can then be used for routing decisions and trace logging.

    """
    lower_title = title.lower()

    if "banned_in_title" in banned_terms:
        for term in banned_terms["banned_in_title"]:
            term_lower = term.lower()
            if _contains_phrase(lower_title, term_lower):
                return True, f"banned_in_title:{term}"

    combined_text = f"{company} {title} {location} {description}".lower()

    if "banned_anywhere" in banned_terms:
        for term in banned_terms["banned_anywhere"]:
            term_lower = term.lower()
            if _contains_phrase(combined_text, term_lower):
                return True, f"banned_anywhere:{term}"

    return False, None
