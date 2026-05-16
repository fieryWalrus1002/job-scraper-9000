from dataclasses import dataclass, field
from typing import Literal, get_args

PrefilterRoute = Literal[
    "remote_filter_candidate",
    "local_candidate",
    "prefilter_reject",
]

PREFILTER_ROUTES: list[str] = list(get_args(PrefilterRoute))
SCHEMA_VERSION = "1.0.0"

DEFAULT_COUNTRY_ALIASES: dict[str, list[str]] = {
    "USA": [
        "US",
        "U.S.",
        "United States",
        "United States of America",
        "America",
        "United States (US)",
    ],
    "Canada": ["Canada"],
    "Mexico": ["Mexico"],
    "United Kingdom": ["UK", "U.K.", "United Kingdom", "Great Britain", "Britain"],
    "Ireland": ["Ireland"],
    "France": ["France", "Paris, France"],
    "Germany": ["Germany"],
    "Netherlands": ["Netherlands"],
    "Sweden": ["Sweden"],
    "Denmark": ["Denmark"],
    "Finland": ["Finland"],
    "Norway": ["Norway"],
    "Spain": ["Spain"],
    "Italy": ["Italy"],
    "Switzerland": ["Switzerland"],
    "Austria": ["Austria"],
    "Belgium": ["Belgium"],
    "Singapore": ["Singapore"],
    "India": ["India"],
    "Australia": ["Australia"],
    "New Zealand": ["New Zealand"],
    "Japan": ["Japan"],
    "South Korea": ["South Korea"],
    "China": ["China"],
    "Israel": ["Israel"],
    "United Arab Emirates": ["UAE", "United Arab Emirates"],
    "Brazil": ["Brazil"],
    "South Africa": ["South Africa"],
}


@dataclass
class CountryDetectionConfig:
    enabled: bool = True
    sources: list[str] = field(default_factory=lambda: ["location", "description"])
    aliases: dict[str, list[str]] = field(default_factory=dict)
    unknown_policy: str = "continue"


@dataclass
class LocalAreaConfig:
    allowed_locations: list[str] = field(default_factory=list)
    home_location: str | None = None


@dataclass
class RoutingConfig:
    route_local_jobs: bool = True
    route_remote_candidates: bool = True
    reject_non_us: bool = True
    prefer_search_params_as_weak_signal: bool = True


@dataclass
class PrefilterConfig:
    country: str = "USA"
    country_detection: CountryDetectionConfig = field(default_factory=CountryDetectionConfig)
    local_area: LocalAreaConfig = field(default_factory=LocalAreaConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
