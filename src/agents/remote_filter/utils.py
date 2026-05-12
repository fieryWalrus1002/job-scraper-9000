import json
import logging
import os
from pathlib import Path

from openai import OpenAI
from pydantic import ValidationError

from .models import RemoteAnalysis

log = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parents[3] / "prompts" / "remote_agent" / "system_prompt_v1.txt"
_PROMPT = _PROMPT_PATH.read_text()


def _get_client(llm_config: dict | None = None) -> tuple[OpenAI, str]:
    cfg = llm_config or {}
    provider = cfg.get("provider", os.environ.get("LLM_PROVIDER", "openai")).lower()
    if provider == "ollama":
        client = OpenAI(
            base_url=cfg.get("base_url", os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")),
            api_key="ollama",
        )
        model = cfg.get("model", os.environ.get("LLM_MODEL", "qwen2.5:14b"))
    else:
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        model = cfg.get("model", os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    return client, model


def analyze_remote(
    job_description: str,
    *,
    llm_config: dict | None = None,
    max_retries: int = 2,
) -> RemoteAnalysis | None:
    """Returns None if the agent fails after retries — caller decides what to do."""
    client, model = _get_client(llm_config)

    for attempt in range(max_retries + 1):
        try:
            response = client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": _PROMPT},
                    {"role": "user", "content": job_description},
                ],
                response_format=RemoteAnalysis,
                temperature=(llm_config or {}).get("temperature", 0.1),
            )
            return response.choices[0].message.parsed
        except ValidationError as exc:
            log.warning("Attempt %d/%d failed validation: %s", attempt + 1, max_retries + 1, exc)
        except Exception as exc:
            log.warning("Attempt %d/%d failed: %s", attempt + 1, max_retries + 1, exc)

    log.error("All %d attempts failed", max_retries + 1)
    return None


def passes_remote_filter(analysis: RemoteAnalysis, config: dict, user_location: str = "USA") -> tuple[bool, str]:
    """Returns (passes, reason)."""
    policy = config["policy_thresholds"]

    if not policy["relocation"]["allow_required_relocation"] and analysis.requires_relocation:
        return False, "requires_relocation"

    if not policy["relocation"]["allow_local_presence_required"] and analysis.requires_local_presence:
        return False, "requires_local_presence"

    if analysis.remote_classification in policy["disallowed_classifications"]:
        return False, f"classification:{analysis.remote_classification}"

    if analysis.remote_classification in policy["travel"]["prohibited_categories"]:
        return False, "travel_too_frequent"

    if (
        analysis.estimated_travel_days_per_year is not None
        and analysis.estimated_travel_days_per_year > policy["travel"]["max_estimated_days_per_year"]
    ):
        return False, f"travel_days_exceeded:{analysis.estimated_travel_days_per_year}"

    if analysis.remote_classification == "unclear":
        if policy["uncertainty"]["on_unclear_classification"] == "reject":
            return False, "agent_uncertain"

    if analysis.location_restrictions:
        loc = user_location.upper()
        for r in analysis.location_restrictions:
            r_upper = r.upper()
            if "US-ONLY" in r_upper or "UNITED STATES" in r_upper or "US ONLY" in r_upper:
                if "US" not in loc and "UNITED STATES" not in loc and "USA" not in loc:
                    return False, "location_restrictions_mismatch"

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
