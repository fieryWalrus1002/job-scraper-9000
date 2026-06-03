"""Salary extraction from free-text job descriptions.

Extracts salary ranges from unstructured text and normalises amounts to
yearly USD integers regardless of source period (hourly, monthly, etc.).
The original period is preserved in salary_period for display purposes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HOURS_PER_YEAR = 2080
_MONTHS_PER_YEAR = 12
_WEEKS_PER_YEAR = 52
_DAYS_PER_YEAR = 260  # 52 × 5


@dataclass
class SalaryResult:
    salary_min_usd: int | None
    salary_max_usd: int | None
    salary_period: str  # 'yearly' | 'hourly' | 'monthly' | 'weekly' | 'daily'


_PERIOD_MULTIPLIERS = {
    "yearly": 1,
    "monthly": _MONTHS_PER_YEAR,
    "weekly": _WEEKS_PER_YEAR,
    "daily": _DAYS_PER_YEAR,
    "hourly": _HOURS_PER_YEAR,
}


def annualise(amount: float, period: str) -> int:
    """Convert an amount in the given period to yearly USD."""
    return round(amount * _PERIOD_MULTIPLIERS.get(period, 1))


# --- Regex patterns, tried in priority order ---

# 1. Hourly: $X/hr, $X-Y/hr, $X–$Y/hour  (unambiguous due to /hr suffix)
_HOURLY = re.compile(
    r"\$\s*([\d]+(?:\.\d+)?)"
    r"(?:\s*[-–—]\s*\$?\s*([\d]+(?:\.\d+)?))?"
    r"\s*/\s*h(?:r|our)\b",
    re.IGNORECASE,
)

# 2. k-range, both sides have $: $200k–$275k, $170k - $190k
_K_RANGE_BOTH = re.compile(
    r"\$\s*([\d]+(?:\.\d+)?)\s*[kK]\s*[-–—]\s*\$\s*([\d]+(?:\.\d+)?)\s*[kK]"
)

# 3. k-range, one $, k only at end: $200-275k  (common recruiter format)
_K_RANGE_ONE = re.compile(
    r"\$\s*([\d]+(?:\.\d+)?)\s*[-–—]\s*([\d]+(?:\.\d+)?)\s*[kK]\b"
)

# 4. Comma-notation range: $100,000 – $150,000
_COMMA_RANGE = re.compile(
    r"\$\s*([\d]{1,3},[\d]{3})\s*[-–—]\s*\$?\s*([\d]{1,3},[\d]{3})"
)

# 5. Single k with salary context nearby: "base $400k", "salary $120k"
_K_SINGLE = re.compile(r"\$\s*([\d]+(?:\.\d+)?)\s*[kK]\b")

_SALARY_CONTEXT = re.compile(
    r"\b(?:base|salary|compensation|pay|compensate|OTE|annual|rate|earn|offer)\b",
    re.IGNORECASE,
)

# Sanity bounds for k-notation singles (reject "$3k signing bonus", "$1000k valuation")
_K_SINGLE_MIN = 40
_K_SINGLE_MAX = 700


def extract_salary(text: str) -> SalaryResult | None:
    """Return the first plausible salary found in text, or None."""
    if not text:
        return None

    # 1. Hourly — unambiguous
    m = _HOURLY.search(text)
    if m:
        lo = round(float(m.group(1)))
        hi = round(float(m.group(2))) if m.group(2) else None
        return SalaryResult(
            salary_min_usd=annualise(lo, "hourly"),
            salary_max_usd=annualise(hi, "hourly") if hi is not None else None,
            salary_period="hourly",
        )

    # 2. k-range (range signal is strong enough; no context guard needed)
    m = _K_RANGE_BOTH.search(text)
    if not m:
        m = _K_RANGE_ONE.search(text)
    if m:
        return SalaryResult(
            salary_min_usd=_k(m.group(1)),
            salary_max_usd=_k(m.group(2)),
            salary_period="yearly",
        )

    # 3. Comma range
    m = _COMMA_RANGE.search(text)
    if m:
        return SalaryResult(
            salary_min_usd=_dollars(m.group(1)),
            salary_max_usd=_dollars(m.group(2)),
            salary_period="yearly",
        )

    # 4. Single k — require salary context and plausible range
    for m in _K_SINGLE.finditer(text):
        val = float(m.group(1))
        if _K_SINGLE_MIN <= val <= _K_SINGLE_MAX and _has_salary_context(
            text, m.start()
        ):
            return SalaryResult(
                salary_min_usd=_k(m.group(1)),
                salary_max_usd=None,
                salary_period="yearly",
            )

    return None


def _k(s: str) -> int:
    return round(float(s) * 1000)


def _dollars(s: str) -> int:
    return int(s.replace(",", ""))


def _has_salary_context(text: str, pos: int, window: int = 80) -> bool:
    lo = max(0, pos - window)
    hi = min(len(text), pos + window)
    return bool(_SALARY_CONTEXT.search(text[lo:hi]))
