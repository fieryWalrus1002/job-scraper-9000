from dataclasses import dataclass
from urllib.parse import urlencode

# LinkedIn f_SB2 param — salary floor filters
SALARY_FLOOR: dict[int, str] = {
    40_000:  "1",
    60_000:  "2",
    80_000:  "3",
    100_000: "4",
    120_000: "5",
}

# LinkedIn f_TPR param — seconds since posting
TIME_DAY   = "r86400"
TIME_WEEK  = "r604800"
TIME_MONTH = "r2592000"
TIME_ANY   = None

# LinkedIn f_E param — experience level codes
EXPERIENCE_INTERNSHIP  = "1"
EXPERIENCE_ENTRY       = "2"
EXPERIENCE_ASSOCIATE   = "3"
EXPERIENCE_MID_SENIOR  = "4"
EXPERIENCE_DIRECTOR    = "5"
EXPERIENCE_EXECUTIVE   = "6"
EXPERIENCE_ALL         = "1,2,3,4,5,6"


@dataclass
class LinkedInSearchQuery:
    keywords: str
    location: str = "United States"
    geo_id: str = "103644278"
    job_type: str = "F"            # F=full-time, P=part-time, C=contract
    experience: str = "2,3,4,5"   # comma-separated LinkedIn experience codes
    workplace: str = "2"           # 1=on-site, 2=remote, 3=hybrid
    time_posted: str | None = TIME_DAY
    salary_floor: int | None = None  # must be a key in SALARY_FLOOR, e.g. 120_000
    sort_by: str = "DD"              # DD=most recent, R=relevance
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
