from dataclasses import dataclass, field
from urllib.parse import urlencode

# LinkedIn f_SB2 param — salary floor filters
SALARY_FLOOR: dict[int, str] = {
    40_000: "1",
    60_000: "2",
    80_000: "3",
    100_000: "4",
    120_000: "5",
}

# LinkedIn f_TPR param — seconds since posting
TIME_DAY = "r86400"
TIME_WEEK = "r604800"
TIME_MONTH = "r2592000"
TIME_ANY = None

# LinkedIn f_E param — experience level codes
EXPERIENCE_INTERNSHIP = "1"
EXPERIENCE_ENTRY = "2"
EXPERIENCE_ASSOCIATE = "3"
EXPERIENCE_MID_SENIOR = "4"
EXPERIENCE_DIRECTOR = "5"
EXPERIENCE_EXECUTIVE = "6"
EXPERIENCE_ALL = "1,2,3,4,5,6"


@dataclass
class SELSearchQuery:
    """
    Query object for SEL (Workday).
    Supports multi-value parameter chaining for worker subtypes and time types.
    """

    location_key: str = "pullman_wa"
    # Peer Review: Default to empty list for multi-select support
    worker_sub_types: list[str] = field(default_factory=lambda: ["regular"])
    time_types: list[str] = field(default_factory=lambda: ["full_time"])
    fetch_descriptions: bool = True

    def to_params(self) -> list[tuple[str, str]]:
        """
        Translates human keys to Workday GUIDs.
        Returns a list of tuples to support duplicate keys in the URL.
        """
        # Mapping dictionaries (Moved here or kept in a central mapping file)
        loc_map = {"pullman_wa": "df72ee3ddefc1018ebf01de718624e22"}
        worker_map = {
            "regular": "96e1096563ef1014e495031ab61a6dff",
            "temporary": "96e1096563ef1014e495069e83966e00",
        }
        time_map = {
            "full_time": "b0630d66f89e1013409e4b1a1a91c123",
            "part_time": "b0630d66f89e1013409e4ae8d2c9c122",
        }

        params = []

        # Add Location
        if self.location_key in loc_map:
            params.append(("locations", loc_map[self.location_key]))

        # Add Chained Worker Sub-Types
        for stype in self.worker_sub_types:
            if stype in worker_map:
                params.append(("workerSubType", worker_map[stype]))

        # Add Chained Time Types
        for ttype in self.time_types:
            if ttype in time_map:
                params.append(("timeType", time_map[ttype]))

        return params

    def to_url(self, base_url: str) -> str:
        """
        Generates the final Workday URL.
        doseq=True is critical for handling the lists of tuples.
        """
        return f"{base_url}?{urlencode(self.to_params(), doseq=True)}"


@dataclass
class LinkedInSearchQuery:
    keywords: str
    location: str = "United States"
    geo_id: str = "103644278"
    job_type: str = "F"  # F=full-time, P=part-time, C=contract
    experience: str = "2,3,4,5"  # comma-separated LinkedIn experience codes
    workplace: str = "2"  # 1=on-site, 2=remote, 3=hybrid
    time_posted: str | None = TIME_DAY
    salary_floor: int | None = None  # must be a key in SALARY_FLOOR, e.g. 120_000
    sort_by: str = "DD"  # DD=most recent, R=relevance
    max_results: int = 100
    fetch_descriptions: bool = True

    def to_params(self, start: int = 0) -> dict:
        params: dict = {
            "keywords": self.keywords,
            "location": self.location,
            "geoId": self.geo_id,
            "f_JT": self.job_type,
            "f_E": self.experience,
            "f_WT": self.workplace,
            "sortBy": self.sort_by,
            "start": start,
        }
        if self.time_posted:
            params["f_TPR"] = self.time_posted
        if self.salary_floor is not None:
            sb2 = SALARY_FLOOR.get(self.salary_floor)
            if sb2:
                params["f_SB2"] = sb2
        return params

    def to_url(self, base: str, start: int = 0) -> str:
        return f"{base}?{urlencode(self.to_params(start=start))}"
