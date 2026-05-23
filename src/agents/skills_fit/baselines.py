"""Non-LLM baseline scorers for skills_fit.

The eval has to beat at least one of these to justify the LLM cost. If a
30-line keyword heuristic hits Spearman ρ = 0.65, the LLM had better do
materially better. The baseline also serves as the floor against which
Variant A (embedding evidence) is measured later.
"""

from .models import Confidence, FitScore, SkillsFitAnalysis


def keyword_overlap_analyze(
    job_description: str,
    *,
    candidate_profile: dict,
    title: str | None = None,
) -> SkillsFitAnalysis:
    """Score 1-5 by weighted overlap of profile skills mentioned in the JD.

    Deliberately dumb. Substring matching, no stemming, no embeddings. Core
    skills weighted 70%, adjacent skills 30%. Maps the [0, 1] overlap ratio
    to a 1-5 band via hand-tuned thresholds.
    """
    text = (title or "") + " " + (job_description or "")
    text_lower = text.lower()

    core = [s for s in candidate_profile.get("core_skills", [])]
    adjacent = [s for s in candidate_profile.get("adjacent_skills", [])]

    core_hits = [s for s in core if s.lower() in text_lower]
    adj_hits = [s for s in adjacent if s.lower() in text_lower]
    core_misses = [s for s in core if s.lower() not in text_lower]

    core_ratio = len(core_hits) / max(len(core), 1)
    adj_ratio = len(adj_hits) / max(len(adjacent), 1)
    weighted = 0.7 * core_ratio + 0.3 * adj_ratio

    score: FitScore = _ratio_to_band(weighted)
    confidence: Confidence = "low" if len(text_lower) < 400 else "medium"

    return SkillsFitAnalysis(
        fit_score=score,
        confidence=confidence,
        score_rationale=(
            f"keyword baseline: {len(core_hits)}/{len(core)} core + "
            f"{len(adj_hits)}/{len(adjacent)} adjacent matched "
            f"(weighted ratio {weighted:.2f})"
        ),
        top_matches=core_hits + adj_hits,
        gaps=core_misses,
        hard_concerns=[],
    )


def _ratio_to_band(ratio: float) -> FitScore:
    if ratio >= 0.8:
        return 5
    if ratio >= 0.6:
        return 4
    if ratio >= 0.4:
        return 3
    if ratio >= 0.2:
        return 2
    return 1
