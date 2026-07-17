import logging
from datetime import date, datetime

log = logging.getLogger(__name__)

# Strings some sources emit to mean "no date". pandas NaT stringifies to "NaT";
# a missing pandas datetime column stringifies to "nan".
_NULL_STRINGS = {"", "nan", "nat", "none", "null"}


def normalize_posted_at(value: object) -> str | None:
    """Normalize a scraper's raw ``posted_at`` to ``YYYY-MM-DD`` or ``None``.

    The pipeline contract for ``posted_at`` is a date-only string. Downstream
    Pydantic (``skills_fit.models.ScoredJobPosting.posted_at: date``) rejects a
    datetime carrying a non-zero time, so a value like
    ``2026-05-11T13:52:29-04:00`` that survives scraping and remote
    classification blows up late — after LLM spend. Sources emit a grab-bag of
    shapes (ISO dates, ISO datetimes with offsets, ``datetime``/``date``
    objects, pandas ``Timestamp``/``NaT``, float ``NaN``), so we funnel them all
    through here at the ``JobPosting`` boundary.
    """
    if value is None:
        return None
    # float NaN and pandas NaT are never equal to themselves. Check this before
    # the isinstance branches: NaT is datetime-like but has no usable date.
    if value != value:  # noqa: PLR0124
        return None
    # datetime is a subclass of date, so check it first. pandas Timestamp
    # subclasses datetime, so this covers it too.
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        # A non-NaN bare float isn't a date shape we understand; drop it rather
        # than guess at a unit (epoch seconds? Excel serial?).
        return None
    s = str(value).strip()
    if s.lower() in _NULL_STRINGS:
        return None
    try:
        # fromisoformat handles both date-only and offset/Z datetimes in 3.11+;
        # .date() drops any time component to satisfy the date-only contract.
        return datetime.fromisoformat(s).date().isoformat()
    except ValueError:
        log.warning("Dropping unparseable posted_at value %r", value)
        return None
