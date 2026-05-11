TIME_MAP: dict[str, str | None] = {
    "day":   "r86400",
    "week":  "r604800",
    "month": "r2592000",
    "any":   None,
}

WORKPLACE_MAP: dict[str, str] = {
    "remote": "2",
    "onsite": "1",
    "hybrid": "3",
}

JOBTYPE_MAP: dict[str, str] = {
    "fulltime": "F",
    "parttime": "P",
    "contract": "C",
}
