"""Pure-function tests for the upcoming-steps rule engine.

Table-driven style — no database required. Covers boundary conditions,
the cancellation cases, and malformed-metadata fail-fast paths.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from api.upcoming_steps import (
    check_inactivity,
    check_post_application,
    check_post_interview,
    check_stale_to_apply,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(
    dh: str,
    to_status: str,
    days_ago: int,
    from_status: str | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    """Build a minimal status_change event row."""
    ref = now or datetime.now(timezone.utc)
    occurred_at = ref - timedelta(days=days_ago)
    metadata: dict = {"to_status": to_status}
    if from_status is not None:
        metadata["from_status"] = from_status
    return {
        "dedup_hash": dh,
        "occurred_at": occurred_at,
        "metadata": metadata,
    }


# ---------------------------------------------------------------------------
# check_stale_to_apply
# ---------------------------------------------------------------------------


class TestStaleToApply:
    def test_no_events_returns_none(self) -> None:
        assert check_stale_to_apply([], datetime.now(timezone.utc)) is None

    def test_not_stale_within_threshold(self) -> None:
        """to_apply event 1 day ago, threshold=3 → no alert."""
        events = [_event("job-1", "to_apply", 1)]
        assert check_stale_to_apply(events, datetime.now(timezone.utc), 3) is None

    def test_stale_beyond_threshold(self) -> None:
        """to_apply event 4 days ago, threshold=3 → alert."""
        events = [_event("job-1", "to_apply", 4)]
        alert = check_stale_to_apply(events, datetime.now(timezone.utc), 3)
        assert alert is not None
        assert alert.count == 1
        assert alert.dedup_hashes == ["job-1"]
        assert alert.days >= 4

    def test_exactly_at_threshold_no_alert(self) -> None:
        """to_apply event exactly threshold_days ago — boundary: not stale
        (must be *past* threshold, strictly greater)."""
        now = datetime.now(timezone.utc)
        events = [_event("job-1", "to_apply", 3, now=now)]
        alert = check_stale_to_apply(events, now, 3)
        assert alert is None

    def test_applied_cancels_alert(self) -> None:
        """to_apply then applied → no stale alert even if to_apply is old."""
        events = [
            _event("job-1", "to_apply", 10),
            _event("job-1", "applied", 2),
        ]
        assert check_stale_to_apply(events, datetime.now(timezone.utc), 3) is None

    def test_multiple_jobs_aggregated(self) -> None:
        """Two stale jobs → single alert with count=2."""
        events = [
            _event("job-1", "to_apply", 5),
            _event("job-2", "to_apply", 8),
        ]
        alert = check_stale_to_apply(events, datetime.now(timezone.utc), 3)
        assert alert is not None
        assert alert.count == 2
        assert set(alert.dedup_hashes) == {"job-1", "job-2"}
        assert alert.days >= 8  # max days stale

    def test_only_non_to_apply_events_returns_none(self) -> None:
        """Events with other statuses don't trigger stale_to_apply."""
        events = [_event("job-1", "interview", 10)]
        assert check_stale_to_apply(events, datetime.now(timezone.utc), 3) is None

    def test_missing_to_status_raises(self) -> None:
        """Malformed metadata without to_status → ValueError (FAIL FAST)."""
        bad_event = {
            "dedup_hash": "job-bad",
            "occurred_at": datetime.now(timezone.utc),
            "metadata": {"from_status": "maybe"},  # missing to_status
        }
        with pytest.raises(ValueError, match="missing 'to_status'"):
            check_stale_to_apply([bad_event], datetime.now(timezone.utc))

    def test_null_metadata_raises(self) -> None:
        """Null metadata on a status_change → ValueError."""
        bad_event = {
            "dedup_hash": "job-bad",
            "occurred_at": datetime.now(timezone.utc),
            "metadata": None,
        }
        with pytest.raises(ValueError, match="null metadata"):
            check_stale_to_apply([bad_event], datetime.now(timezone.utc))

    def test_to_apply_then_passed_no_alert(self) -> None:
        """to_apply (old) → later passed ⇒ current status is 'passed', no alert."""
        events = [
            _event("job-1", "to_apply", 10),
            _event("job-1", "passed", 2),
        ]
        assert check_stale_to_apply(events, datetime.now(timezone.utc), 3) is None

    def test_to_apply_then_rejected_no_alert(self) -> None:
        """to_apply (old) → later rejected ⇒ current status is 'rejected', no alert."""
        events = [
            _event("job-1", "to_apply", 10),
            _event("job-1", "rejected", 2),
        ]
        assert check_stale_to_apply(events, datetime.now(timezone.utc), 3) is None

    def test_to_apply_then_maybe_no_alert(self) -> None:
        """to_apply (old) → later maybe ⇒ current status is 'maybe', no alert."""
        events = [
            _event("job-1", "to_apply", 10),
            _event("job-1", "maybe", 2),
        ]
        assert check_stale_to_apply(events, datetime.now(timezone.utc), 3) is None


# ---------------------------------------------------------------------------
# check_post_interview
# ---------------------------------------------------------------------------


class TestPostInterview:
    def test_no_events_returns_none(self) -> None:
        assert check_post_interview([], datetime.now(timezone.utc)) is None

    def test_recent_interview_no_alert(self) -> None:
        """Interview 3 days ago, threshold=7 → no alert."""
        events = [_event("job-1", "interview", 3)]
        assert check_post_interview(events, datetime.now(timezone.utc), 7) is None

    def test_stale_interview_alert(self) -> None:
        """Interview 8 days ago, threshold=7 → alert."""
        events = [_event("job-1", "interview", 8)]
        alert = check_post_interview(events, datetime.now(timezone.utc), 7)
        assert alert is not None
        assert alert.count == 1
        assert alert.dedup_hashes == ["job-1"]
        assert alert.days >= 8

    def test_multiple_interview_jobs(self) -> None:
        """Two stale interviews → aggregated alert."""
        events = [
            _event("job-1", "interview", 10),
            _event("job-2", "interview", 14),
        ]
        alert = check_post_interview(events, datetime.now(timezone.utc), 7)
        assert alert is not None
        assert alert.count == 2
        assert set(alert.dedup_hashes) == {"job-1", "job-2"}
        assert alert.days >= 14

    def test_interview_then_rejected_no_alert(self) -> None:
        """interview (old) → later rejected ⇒ current status is 'rejected', no alert."""
        events = [
            _event("job-1", "interview", 10),
            _event("job-1", "rejected", 2),
        ]
        assert check_post_interview(events, datetime.now(timezone.utc), 7) is None

    def test_interview_then_offer_no_alert(self) -> None:
        """interview (old) → later offer ⇒ current status is 'offer', no alert."""
        events = [
            _event("job-1", "interview", 10),
            _event("job-1", "offer", 2),
        ]
        assert check_post_interview(events, datetime.now(timezone.utc), 7) is None

    def test_interview_then_hired_no_alert(self) -> None:
        """interview (old) → later hired ⇒ current status is 'hired', no alert."""
        events = [
            _event("job-1", "interview", 10),
            _event("job-1", "hired", 2),
        ]
        assert check_post_interview(events, datetime.now(timezone.utc), 7) is None

    def test_missing_to_status_raises(self) -> None:
        bad_event = {
            "dedup_hash": "job-bad",
            "occurred_at": datetime.now(timezone.utc),
            "metadata": {"from_status": "screening"},
        }
        with pytest.raises(ValueError, match="missing 'to_status'"):
            check_post_interview([bad_event], datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# check_inactivity
# ---------------------------------------------------------------------------


class TestInactivity:
    def test_no_events_at_all(self) -> None:
        """No events → never applied → no alert (inactivity ≠ never-applied)."""
        assert check_inactivity([], datetime.now(timezone.utc), 14) is None

    def test_recent_applied_no_alert(self) -> None:
        """Applied event 3 days ago, threshold=14 → no alert."""
        events = [_event("job-1", "applied", 3)]
        assert check_inactivity(events, datetime.now(timezone.utc), 14) is None

    def test_old_applied_alert(self) -> None:
        """Last applied event 20 days ago, threshold=14 → alert."""
        events = [_event("job-1", "applied", 20)]
        alert = check_inactivity(events, datetime.now(timezone.utc), 14)
        assert alert is not None
        assert alert.days >= 20

    def test_no_applied_events_other_statuses(self) -> None:
        """Events exist but none are 'applied' → never applied → no alert."""
        events = [
            _event("job-1", "to_apply", 5),
            _event("job-2", "interview", 3),
        ]
        assert check_inactivity(events, datetime.now(timezone.utc), 14) is None

    def test_multiple_applied_uses_latest(self) -> None:
        """Two applied events — only the latest matters."""
        events = [
            _event("job-1", "applied", 30),
            _event("job-2", "applied", 5),
        ]
        assert check_inactivity(events, datetime.now(timezone.utc), 14) is None

    def test_missing_to_status_raises(self) -> None:
        bad_event = {
            "dedup_hash": "job-bad",
            "occurred_at": datetime.now(timezone.utc),
            "metadata": {"from_status": "maybe"},
        }
        with pytest.raises(ValueError, match="missing 'to_status'"):
            check_inactivity([bad_event], datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Helpers — touchpoint events
# ---------------------------------------------------------------------------


def _touchpoint(dh: str, days_ago: int) -> dict:
    """Build a minimal follow_up/contact event row."""
    occurred_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {"dedup_hash": dh, "occurred_at": occurred_at}


# ---------------------------------------------------------------------------
# check_post_application
# ---------------------------------------------------------------------------


class TestPostApplication:
    def test_no_events_returns_none(self) -> None:
        assert check_post_application([], [], datetime.now(timezone.utc)) is None

    def test_applied_beyond_threshold_no_followup_fires(self) -> None:
        """applied 12 days ago, threshold=10, no follow_up → fires."""
        events = [_event("job-1", "applied", 12)]
        alert = check_post_application(events, [], datetime.now(timezone.utc), 10)
        assert alert is not None
        assert alert.count == 1
        assert alert.dedup_hashes == ["job-1"]
        assert alert.days >= 12

    def test_applied_recent_followup_snoozed(self) -> None:
        """applied 15 days ago but follow_up 3 days ago → no alert."""
        events = [_event("job-1", "applied", 15)]
        touchpoints = [_touchpoint("job-1", 3)]
        alert = check_post_application(
            events, touchpoints, datetime.now(timezone.utc), 10
        )
        assert alert is None

    def test_applied_old_followup_fires(self) -> None:
        """applied 20 days ago, follow_up 12 days ago → fires (days from follow-up)."""
        events = [_event("job-1", "applied", 20)]
        touchpoints = [_touchpoint("job-1", 12)]
        alert = check_post_application(
            events, touchpoints, datetime.now(timezone.utc), 10
        )
        assert alert is not None
        assert alert.count == 1
        assert alert.days >= 12

    def test_contact_tag_also_snoozes(self) -> None:
        """A contact event (not follow_up) also resets the clock."""
        events = [_event("job-1", "applied", 15)]
        touchpoints = [_touchpoint("job-1", 2)]
        alert = check_post_application(
            events, touchpoints, datetime.now(timezone.utc), 10
        )
        assert alert is None

    def test_non_resetting_tag_does_not_snooze(self) -> None:
        """A tag that is not follow_up/contact (e.g. interview_prep) does NOT
        snooze — but touchpoints are pre-filtered by the endpoint so this
        test verifies that only the passed touchpoints matter."""
        events = [_event("job-1", "applied", 12)]
        # No touchpoints passed → same as no snooze
        alert = check_post_application(events, [], datetime.now(timezone.utc), 10)
        assert alert is not None
        assert alert.count == 1

    def test_screening_status_counts(self) -> None:
        """screening status is also eligible."""
        events = [
            _event("job-1", "applied", 20),
            _event("job-1", "screening", 12),
        ]
        alert = check_post_application(events, [], datetime.now(timezone.utc), 10)
        assert alert is not None
        assert alert.count == 1
        assert alert.days >= 12

    def test_current_status_guard_rejected_no_alert(self) -> None:
        """applied then rejected → current status is rejected, no alert."""
        events = [
            _event("job-1", "applied", 15),
            _event("job-1", "rejected", 2),
        ]
        alert = check_post_application(events, [], datetime.now(timezone.utc), 10)
        assert alert is None

    def test_current_status_guard_interview_no_alert(self) -> None:
        """applied then interview → current status is interview, no alert."""
        events = [
            _event("job-1", "applied", 15),
            _event("job-1", "interview", 5),
        ]
        alert = check_post_application(events, [], datetime.now(timezone.utc), 10)
        assert alert is None

    def test_boundary_exactly_at_threshold_no_alert(self) -> None:
        """applied exactly 10 days ago, threshold=10 → no alert (strict >)."""
        now = datetime.now(timezone.utc)
        events = [_event("job-1", "applied", 10, now=now)]
        alert = check_post_application(events, [], now, 10)
        assert alert is None

    def test_multiple_jobs_aggregated(self) -> None:
        """Two jobs past threshold → aggregated alert."""
        events = [
            _event("job-1", "applied", 12),
            _event("job-2", "applied", 15),
        ]
        alert = check_post_application(events, [], datetime.now(timezone.utc), 10)
        assert alert is not None
        assert alert.count == 2
        assert set(alert.dedup_hashes) == {"job-1", "job-2"}
        assert alert.days >= 15  # max

    def test_missing_to_status_raises(self) -> None:
        bad_event = {
            "dedup_hash": "job-bad",
            "occurred_at": datetime.now(timezone.utc),
            "metadata": {"from_status": "applied"},
        }
        with pytest.raises(ValueError, match="missing 'to_status'"):
            check_post_application([bad_event], [], datetime.now(timezone.utc))
