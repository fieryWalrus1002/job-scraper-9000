import json
import logging
import os
from pathlib import Path

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


def _get_client(llm_config: dict | None = None) -> tuple[OpenAI, str]:
    cfg = llm_config or {}
    provider = cfg.get("provider", os.environ.get("LLM_PROVIDER", "openai")).lower()
    if provider == "ollama":
        client = OpenAI(
            base_url=cfg.get(
                "base_url",
                os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            ),
            api_key="ollama",
        )
        model = cfg.get("model", os.environ.get("LLM_MODEL", "qwen2.5:14b"))
    else:
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        model = cfg.get("model", os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    return client, model


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
) -> RemoteAnalysis | None:
    """Returns None if the agent fails after retries — caller decides what to do."""
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


def dedup_jobs(jobs: list[dict]) -> tuple[list[dict], int]:
    """Dedup by `dedup_hash` (fallback: `source_job_id`); keep first occurrence.

    Returns (deduped_jobs, dropped_count). Jobs missing both keys pass through
    untouched so they're never silently dropped.
    """
    seen: set[str] = set()
    deduped: list[dict] = []
    for job in jobs:
        key = job.get("dedup_hash") or job.get("source_job_id")
        if not key:
            deduped.append(job)
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append(job)
    return deduped, len(jobs) - len(deduped)


def resolve_llm_model(llm_config: dict | None = None) -> str:
    """Return the model name that `_get_client` would use, for cache keying."""
    cfg = llm_config or {}
    provider = cfg.get("provider", os.environ.get("LLM_PROVIDER", "openai")).lower()
    default = "qwen2.5:14b" if provider == "ollama" else "gpt-4o-mini"
    return cfg.get("model", os.environ.get("LLM_MODEL", default))
