"""Smoke tests for the keyword-overlap baseline scorer."""

from agents.skills_fit.baselines import keyword_overlap_analyze
from agents.skills_fit.models import SkillsFitAnalysis


PROFILE = {
    "core_skills": ["Python", "C++", "Applied ML", "Data engineering"],
    "adjacent_skills": ["PyTorch", "Docker", "AWS"],
}


def test_returns_skills_fit_analysis():
    out = keyword_overlap_analyze(
        "We need a Python engineer with PyTorch experience.",
        candidate_profile=PROFILE,
    )
    assert isinstance(out, SkillsFitAnalysis)


def test_no_overlap_yields_low_score():
    out = keyword_overlap_analyze(
        "Senior RPG developer with PL/I and JCL on z/OS mainframe.",
        candidate_profile=PROFILE,
    )
    assert out.fit_score == 1
    assert out.top_matches == []


def test_strong_overlap_yields_high_score():
    out = keyword_overlap_analyze(
        "Python engineer building Applied ML systems. C++ background helpful. "
        "Stack: PyTorch, Docker, AWS. Data engineering experience required.",
        candidate_profile=PROFILE,
    )
    assert out.fit_score >= 4
    assert "Python" in out.top_matches
    assert "C++" in out.top_matches


def test_partial_overlap_yields_mid_score():
    out = keyword_overlap_analyze(
        "Looking for a Python engineer. Some Docker experience nice to have.",
        candidate_profile=PROFILE,
    )
    # 1/4 core (Python), 1/3 adjacent (Docker)
    # weighted = 0.7 * 0.25 + 0.3 * 0.333 = 0.175 + 0.1 = 0.275 → band 2
    assert out.fit_score == 2


def test_top_matches_contains_only_matched_skills():
    out = keyword_overlap_analyze(
        "Python and C++ role. No ML.",
        candidate_profile=PROFILE,
    )
    assert "Python" in out.top_matches
    assert "C++" in out.top_matches
    assert "Applied ML" not in out.top_matches


def test_gaps_contains_unmatched_core_skills():
    out = keyword_overlap_analyze(
        "Python role only.",
        candidate_profile=PROFILE,
    )
    assert "Python" not in out.gaps
    assert set(out.gaps) >= {"C++", "Applied ML", "Data engineering"}


def test_title_text_is_searched_too():
    # Skill mentioned in title but not body still counts as a hit
    out = keyword_overlap_analyze(
        "Apply if interested.",
        candidate_profile=PROFILE,
        title="Senior Python Engineer",
    )
    assert "Python" in out.top_matches


def test_short_description_yields_low_confidence():
    out = keyword_overlap_analyze(
        "Python role.",
        candidate_profile=PROFILE,
    )
    assert out.confidence == "low"


def test_empty_profile_doesnt_crash():
    out = keyword_overlap_analyze(
        "Python role.",
        candidate_profile={},
    )
    assert isinstance(out, SkillsFitAnalysis)
    assert out.fit_score == 1
