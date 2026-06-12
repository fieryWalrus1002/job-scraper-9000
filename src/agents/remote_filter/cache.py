from pathlib import Path

from utils.analysis_cache import AnalysisCache as _AnalysisCacheBase

from .models import RemoteAnalysis

DEFAULT_CACHE_PATH = Path("data/cache/remote_filter_analyses.jsonl")


class AnalysisCache(_AnalysisCacheBase[RemoteAnalysis]):
    """Across-batch cache for remote-filter classifications.

    Composite key: (dedup_hash, prompt_hash, provider, model, context_fp).
    Any change to the prompt, the provider/model pair, or the search-context
    fields the prompt reads (keywords, workplace, job_type, user_timezone)
    changes the key and forces a miss — no manual invalidation needed.
    """

    KEY_FIELDS = ("dedup_hash", "prompt_hash", "provider", "model", "context_fp")
    ANALYSIS_MODEL = RemoteAnalysis
    DEFAULT_PATH = DEFAULT_CACHE_PATH
