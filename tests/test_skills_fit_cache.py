import json

from agents.skills_fit.cache import AnalysisCache
from agents.skills_fit.models import SkillsFitAnalysis


def make_analysis(score: int = 4) -> SkillsFitAnalysis:
    return SkillsFitAnalysis(
        fit_score=score,
        confidence="high",
        score_rationale="Strong fit",
        top_matches=["Python"],
        gaps=["None"],
        hard_concerns=[],
    )


def test_analysis_cache_round_trip_and_profile_version_invalidation(tmp_path):
    cache_path = tmp_path / "skills_fit_cache.jsonl"
    cache = AnalysisCache(cache_path)
    analysis = make_analysis(5)

    cache.put(
        dedup_hash="hash-a",
        prompt_hash="prompt-1",
        provider="openai",
        model="gpt-4o-mini",
        profile_version="2026-06-12.deadbeefcafe",
        analysis=analysis,
    )

    hit = cache.get(
        dedup_hash="hash-a",
        prompt_hash="prompt-1",
        provider="openai",
        model="gpt-4o-mini",
        profile_version="2026-06-12.deadbeefcafe",
    )
    miss = cache.get(
        dedup_hash="hash-a",
        prompt_hash="prompt-1",
        provider="openai",
        model="gpt-4o-mini",
        profile_version="2026-06-13.0000000000ff",
    )

    assert hit is not None
    assert hit.fit_score == 5
    assert miss is None


def test_analysis_cache_skips_malformed_lines(tmp_path, caplog):
    cache_path = tmp_path / "skills_fit_cache.jsonl"
    cache_path.write_text(
        "not json\n"
        + json.dumps(
            {
                "key": "hash-a|prompt-1|openai|gpt-4o-mini|2026-06-12.deadbeefcafe",
                "analysis": make_analysis().model_dump(),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    cache = AnalysisCache(cache_path)
    hit = cache.get(
        dedup_hash="hash-a",
        prompt_hash="prompt-1",
        provider="openai",
        model="gpt-4o-mini",
        profile_version="2026-06-12.deadbeefcafe",
    )

    assert "Skipping malformed cache line" in caplog.text
    assert hit is not None
    assert hit.fit_score == 4
