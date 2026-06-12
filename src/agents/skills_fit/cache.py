from pathlib import Path

from utils.analysis_cache import AnalysisCache as _AnalysisCacheBase

from .models import SkillsFitAnalysis

DEFAULT_CACHE_PATH = Path("data/cache/skills_fit_analyses.jsonl")


class AnalysisCache(_AnalysisCacheBase[SkillsFitAnalysis]):
    """Across-batch cache for skills-fit analyses.

    Composite key: (dedup_hash, prompt_hash, provider, model, profile_version).
    Any change to the prompt, the provider/model pair, or the profile
    content (caught by Phase 12's content-hashed `profile_version`) changes
    the key and forces a miss — no manual invalidation needed.
    """

    KEY_FIELDS = ("dedup_hash", "prompt_hash", "provider", "model", "profile_version")
    ANALYSIS_MODEL = SkillsFitAnalysis
    DEFAULT_PATH = DEFAULT_CACHE_PATH
