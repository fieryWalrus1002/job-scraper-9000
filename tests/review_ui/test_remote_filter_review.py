import pytest

from review_ui.remote_filter_review import (
    MissingAnalysisError,
    extract_remote_analysis,
    proposed_classification,
    suggested_verdict,
    validate_active_label,
)


def test_extracts_production_remote_analysis():
    analysis = {"remote_classification": "remote", "reasoning_trace": "ok"}

    assert extract_remote_analysis({"_remote_analysis": analysis}) == analysis


def test_rejects_legacy_label_from_production_analysis():
    analysis = {
        "remote_classification": "onsite_disguised",
        "reasoning_trace": "office",
    }

    assert proposed_classification(analysis) is None
    assert suggested_verdict(None) == "unknown"


def test_legacy_teacher_response_shape_is_not_review_input():
    job = {
        "response": {
            "body": {"choices": [{"message": {"content": "{}"}}]},
        }
    }

    with pytest.raises(MissingAnalysisError, match="production _remote_analysis"):
        extract_remote_analysis(job)


def test_missing_analysis_fails_loudly():
    with pytest.raises(MissingAnalysisError, match="production _remote_analysis"):
        extract_remote_analysis({"title": "No proposal"})


def test_review_labels_are_active_3way_only():
    validate_active_label("remote")

    with pytest.raises(ValueError, match="active 3-way axis"):
        validate_active_label("unclear")
