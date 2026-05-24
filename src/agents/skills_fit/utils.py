import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import yaml
from openai import OpenAI
from pydantic import ValidationError

from .models import SkillsFitAnalysis

log = logging.getLogger(__name__)


def _resolve_prompt_path() -> Path:
    """Return the active skills-fit prompt path in source trees or installed wheels."""
    relative = Path("prompts") / "skills_fit" / "system_prompt.txt"
    candidates = [
        Path(__file__).parents[3] / relative,
        Path(__file__).parents[2] / relative,
        Path.cwd() / relative,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Skills-fit prompt not found. Checked: " + ", ".join(str(c) for c in candidates)
    )


SKILLS_FIT_PROMPT_PATH = _resolve_prompt_path()


@lru_cache(maxsize=None)
def _load_prompt(path: Path) -> str:
    return path.read_text()


def load_candidate_profile(path: str | Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(os.path.expandvars(f.read())) or {}


def _to_list(val: object) -> list[str]:
    """Coerce a profile field to a join-safe list of strings.

    Guards against two YAML shapes that would otherwise produce garbage in
    the prompt: scalar values (would iterate characters in join()) and
    non-string list items (would TypeError in join()).
    """
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x) for x in val]
    return [str(val)]


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
        # Per-component API keys: llm.api_key_env names which env var to read.
        api_key_env = cfg.get("api_key_env", "OPENAI_API_KEY")
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{api_key_env} is not set in environment "
                "(configure via llm.api_key_env in the agent YAML; "
                "defaults to OPENAI_API_KEY)"
            )
        client = OpenAI(api_key=api_key)
        model = cfg.get("model", os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    return client, model


def _format_profile_block(profile: dict) -> str:
    """Render the candidate profile YAML as a compact text block for the prompt."""
    lines = ["=== CANDIDATE PROFILE ==="]
    if summary := profile.get("summary"):
        lines.append(f"Summary: {summary.strip()}")
    if level := profile.get("level"):
        lines.append(f"Level: {level}")
    if education := _to_list(profile.get("education")):
        lines.append("Education: " + "; ".join(education))
    if core := _to_list(profile.get("core_skills")):
        lines.append("Core skills: " + ", ".join(core))
    if adj := _to_list(profile.get("adjacent_skills")):
        lines.append("Adjacent skills: " + ", ".join(adj))
    if domains := _to_list(profile.get("preferred_domains")):
        lines.append("Preferred domains: " + ", ".join(domains))
    if avoid := _to_list(profile.get("avoided_domains")):
        lines.append("Avoided domains: " + ", ".join(avoid))
    if constraints := _to_list(profile.get("constraints")):
        lines.append("Constraints: " + "; ".join(constraints))
    return "\n".join(lines)


def _build_user_message(
    description: str,
    profile: dict,
    *,
    title: str | None = None,
    location: str | None = None,
) -> str:
    parts = [_format_profile_block(profile), "=== JOB POSTING ==="]
    if title:
        parts.append(f"Title: {title}")
    if location:
        parts.append(f"Location: {location}")
    parts.append("")
    parts.append(description)
    return "\n".join(parts)


def _extract_usage(usage_obj: Any) -> dict[str, int]:
    """Pull token counts out of an OpenAI ``ChatCompletion.usage`` object."""
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


def analyze_skills_fit(
    job_description: str,
    *,
    candidate_profile: dict,
    title: str | None = None,
    location: str | None = None,
    llm_config: dict | None = None,
    prompt_path: str | Path | None = None,
    max_retries: int = 2,
    usage_callback: Callable[[dict[str, int]], None] | None = None,
) -> SkillsFitAnalysis | None:
    """Run the structured LLM call. Returns None if the agent fails after retries."""
    client, model = _get_client(llm_config)
    user_message = _build_user_message(
        job_description, candidate_profile, title=title, location=location
    )
    prompt = _load_prompt(Path(prompt_path) if prompt_path else SKILLS_FIT_PROMPT_PATH)

    for attempt in range(max_retries + 1):
        try:
            response = client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format=SkillsFitAnalysis,
                temperature=(llm_config or {}).get("temperature", 0.1),
            )
            if usage_callback is not None:
                usage_callback(_extract_usage(response.usage))
            return response.choices[0].message.parsed
        except ValidationError as exc:
            log.warning(
                "Attempt %d/%d failed validation: %s",
                attempt + 1,
                max_retries + 1,
                exc,
            )
        except Exception as exc:
            log.warning("Attempt %d/%d failed: %s", attempt + 1, max_retries + 1, exc)

    log.error("All %d attempts failed", max_retries + 1)
    return None


def load_gold(path: Path) -> list[dict]:
    """Last entry per dedup_hash wins (re-reviews override)."""
    seen: dict[str, dict] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            key = r.get("dedup_hash") or r.get("source_url") or str(id(r))
            seen[key] = r
    return list(seen.values())
