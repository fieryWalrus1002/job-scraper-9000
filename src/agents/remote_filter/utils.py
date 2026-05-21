import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI
from pydantic import ValidationError

from .models import RemoteAnalysis

log = logging.getLogger(__name__)

def _resolve_prompt_path() -> Path:
    """Return the active remote-filter prompt path in source trees or installed wheels."""
    relative = Path("prompts") / "remote_agent" / "system_prompt.txt"
    candidates = [
        Path(__file__).parents[3] / relative,  # repo root when running from src/
        Path(__file__).parents[2] / relative,  # site-packages when prompts are wheel data
        Path.cwd() / relative,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Remote filter prompt not found. Checked: "
        + ", ".join(str(candidate) for candidate in candidates)
    )


REMOTE_FILTER_PROMPT_PATH = _resolve_prompt_path()
_PROMPT = REMOTE_FILTER_PROMPT_PATH.read_text()


def resolve_provider_and_model(llm_config: dict | None = None) -> tuple[str, str]:
    """Single source of truth for which (provider, model) a config resolves to.

    Both `_get_client` (inference) and `resolve_llm_model` (cache keying) route
    through this so a config drift can't cause the cache key to lie about which
    model produced the analysis.
    """
    cfg = llm_config or {}
    provider = cfg.get("provider", os.environ.get("LLM_PROVIDER", "openai")).lower()
    default_model = "qwen2.5:14b" if provider == "ollama" else "gpt-4o-mini"
    model = cfg.get("model", os.environ.get("LLM_MODEL", default_model))
    return provider, model


def _get_client(llm_config: dict | None = None) -> tuple[OpenAI, str]:
    cfg = llm_config or {}
    provider, model = resolve_provider_and_model(cfg)
    if provider == "ollama":
        client = OpenAI(
            base_url=cfg.get(
                "base_url",
                os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            ),
            api_key="ollama",
        )
    else:
        # Per-component API keys: `llm.api_key_env` in the agent YAML names
        # which env var to read. Defaults to OPENAI_API_KEY for back-compat.
        api_key_env = cfg.get("api_key_env", "OPENAI_API_KEY")
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{api_key_env} is not set in environment "
                "(configured via llm.api_key_env in the agent YAML; "
                "defaults to OPENAI_API_KEY)"
            )
        client = OpenAI(api_key=api_key)
    return client, model


def _extract_usage(usage_obj: Any) -> dict[str, int]:
    """Pull token counts out of an OpenAI ``ChatCompletion.usage`` object.

    Returns zero-valued dict if usage data is absent (e.g., some local-LLM
    servers don't emit it). Cached input tokens come from the nested
    ``prompt_tokens_details.cached_tokens`` introduced with prompt caching.
    """
    if usage_obj is None:
        return {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    cached = 0
    details = getattr(usage_obj, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
    return {
        "input_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
        "cached_input_tokens": cached,
        "output_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
    }


def _build_user_message(
    description: str,
    search_context: dict | None,
    location: str | None = None,
    title: str | None = None,
) -> str:
    """Prepend title, location, and search context so the model can factor them into its reasoning."""
    parts = []
    if title:
        parts.append(f"Job title: {title}")
    if location:
        parts.append(f"Location field: {location}")
    if search_context:
        ctx = []
        if kw := search_context.get("keywords"):
            ctx.append(f'keywords="{kw}"')
        if wp := search_context.get("workplace"):
            ctx.append(f"workplace_filter={wp}")
        if jt := search_context.get("job_type"):
            ctx.append(f"job_type={jt}")
        if tz := search_context.get("user_timezone"):
            ctx.append(f"candidate_timezone={tz}")
        if ctx:
            parts.append(f"Search context: {', '.join(ctx)}")
    if not parts:
        return description
    return "\n".join(f"[{p}]" for p in parts) + "\n\n---\n\n" + description


def analyze_remote(
    job_description: str,
    *,
    title: str | None = None,
    location: str | None = None,
    search_context: dict | None = None,
    llm_config: dict | None = None,
    max_retries: int = 2,
    usage_callback: Callable[[dict[str, int]], None] | None = None,
) -> RemoteAnalysis | None:
    """Returns None if the agent fails after retries — caller decides what to do.

    If ``usage_callback`` is provided, it's called with a dict of token counts
    (``input_tokens``, ``cached_input_tokens``, ``output_tokens``) on each
    successful API call. Wire it to ``RunTracker.add_token_usage`` for telemetry.
    """
    client, model = _get_client(llm_config)
    user_message = _build_user_message(job_description, search_context, location, title)

    for attempt in range(max_retries + 1):
        try:
            response = client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": _PROMPT},
                    {"role": "user", "content": user_message},
                ],
                response_format=RemoteAnalysis,
                temperature=(llm_config or {}).get("temperature", 0.1),
            )
            if usage_callback is not None:
                usage_callback(_extract_usage(response.usage))
            return response.choices[0].message.parsed
        except ValidationError as exc:
            log.warning(
                "Attempt %d/%d failed validation: %s", attempt + 1, max_retries + 1, exc
            )
        except Exception as exc:
            log.warning("Attempt %d/%d failed: %s", attempt + 1, max_retries + 1, exc)

    log.error("All %d attempts failed", max_retries + 1)
    return None


def passes_remote_filter(
    analysis: RemoteAnalysis, config: dict, user_location: str = "USA"
) -> tuple[bool, str]:
    """Returns (passes, reason)."""
    policy = config["policy_thresholds"]

    if (
        not policy["relocation"]["allow_required_relocation"]
        and analysis.requires_relocation
    ):
        return False, "requires_relocation"

    if (
        not policy["relocation"]["allow_local_presence_required"]
        and analysis.requires_local_presence
    ):
        return False, "requires_local_presence"

    if analysis.remote_classification in policy["disallowed_classifications"]:
        return False, f"classification:{analysis.remote_classification}"

    if analysis.remote_classification in policy["travel"]["prohibited_categories"]:
        return False, "travel_too_frequent"

    if (
        analysis.estimated_travel_days_per_year is not None
        and analysis.estimated_travel_days_per_year
        > policy["travel"]["max_estimated_days_per_year"]
    ):
        return False, f"travel_days_exceeded:{analysis.estimated_travel_days_per_year}"

    if analysis.remote_classification == "unclear":
        if policy["uncertainty"]["on_unclear_classification"] == "reject":
            return False, "agent_uncertain"

    if analysis.location_restrictions:
        loc = user_location.upper()
        for r in analysis.location_restrictions:
            r_upper = r.upper()
            if (
                "US-ONLY" in r_upper
                or "UNITED STATES" in r_upper
                or "US ONLY" in r_upper
            ):
                if "US" not in loc and "UNITED STATES" not in loc and "USA" not in loc:
                    return False, "location_restrictions_mismatch"

    if analysis.timezone_requirements:
        tz_policy = policy.get("timezone", {})
        rejected_keywords = [
            k.upper() for k in tz_policy.get("rejected_timezone_keywords", [])
        ]
        if rejected_keywords:
            for req in analysis.timezone_requirements:
                req_upper = req.upper()
                if any(kw in req_upper for kw in rejected_keywords):
                    return False, f"timezone_mismatch:{req}"

    return True, "passed"


def load_raw_jobs(path: Path) -> list[dict]:
    paths = [path] if path.is_file() else sorted(path.glob("*.jsonl"))
    jobs = []
    for p in paths:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    jobs.append(json.loads(line))
    return jobs


def resolve_llm_model(llm_config: dict | None = None) -> str:
    """Return the model name that `_get_client` would use, for cache keying."""
    return resolve_provider_and_model(llm_config)[1]


# Fields of `search_context` that `_build_user_message` actually reads. Keep
# this in sync with that function — anything that affects the LLM prompt must
# affect the cache key, or stale analyses leak across runs.
_CONTEXT_FIELDS = ("keywords", "workplace", "job_type", "user_timezone")


def context_fingerprint(search_context: dict | None) -> str:
    """8-hex fingerprint over search-context fields that affect the LLM prompt.

    Folded into the analysis cache key so a change in keywords, workplace,
    job_type, or user_timezone invalidates the cache rather than serving an
    analysis produced under different context. Returns `"none"` when no
    relevant context is present, matching `_build_user_message`'s no-op path.
    """
    if not search_context:
        return "none"
    relevant: dict[str, object] = {}
    for k in _CONTEXT_FIELDS:
        v = search_context.get(k)
        if v:
            relevant[k] = v
    if not relevant:
        return "none"
    canonical = json.dumps(relevant, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:8]
