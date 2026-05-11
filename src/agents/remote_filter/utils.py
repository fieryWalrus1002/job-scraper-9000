import logging
import os

from openai import OpenAI
from pydantic import ValidationError

from .models import RemoteAnalysis, UserPreferences

log = logging.getLogger(__name__)

_PROMPT = """You are analyzing a job posting to extract its remote work policy.
You will produce a structured analysis in JSON format.

Read the posting carefully. Look for:

1. Explicit statements about remote vs. onsite vs. hybrid work
2. Location requirements ("must reside in X", "within commuting distance of Y")
3. Travel expectations (frequency, purpose, percentage of time)
4. Relocation requirements (immediate or future)
5. Time zone or geographic restrictions

When the posting is ambiguous, prefer "unclear" over guessing.
Confidence should be "low" if you're making inferences rather than quoting explicit statements.

Common patterns to recognize:
- "Remote" in the title but "must be located in [city]" in the body → onsite_disguised, requires_local_presence=true
- "Remote with quarterly all-hands" → remote_with_quarterly_travel
- "Hybrid" or "X days per week in office" → hybrid
- "US-based remote" → fully_remote, location_restrictions=["US-only"]
- "Open to remote candidates in [list of states]" → location_restricted
- "Quarterly on-site meetings" → remote_with_quarterly_travel, NOT hybrid

For travel_description, quote or paraphrase the relevant phrase from the posting. Don't editorialize.

For estimated_travel_days_per_year:
- "Quarterly meetings" → 4
- "Monthly meetings" → 12
- "10% travel" → 25
- "Occasional travel" → 6
- If unspecified, leave null

Return ONLY valid JSON matching the schema. No commentary outside the JSON."""


def _get_client() -> tuple[OpenAI, str]:
    """Return (client, model) configured for the active provider."""
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()

    if provider == "ollama":
        client = OpenAI(
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            api_key="ollama",
        )
        model = os.environ.get("LLM_MODEL", "qwen2.5:14b")
    else:
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    return client, model


def analyze_remote(
    job_description: str,
    *,
    max_retries: int = 2,
) -> RemoteAnalysis | None:
    """
    Analyze a job description's remote work policy.
    Returns None if the agent fails after retries — caller decides what to do.
    """
    client, model = _get_client()

    for attempt in range(max_retries + 1):
        try:
            response = client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": _PROMPT},
                    {"role": "user", "content": job_description},
                ],
                response_format=RemoteAnalysis,
                temperature=0.1,
            )
            return response.choices[0].message.parsed
        except ValidationError as exc:
            log.warning("Attempt %d/%d failed validation: %s", attempt + 1, max_retries + 1, exc)
        except Exception as exc:
            log.warning("Attempt %d/%d failed: %s", attempt + 1, max_retries + 1, exc)

    log.error("All %d attempts failed", max_retries + 1)
    return None


def _location_compatible(restrictions: list[str], user_location: str) -> bool:
    loc = user_location.upper()
    for r in restrictions:
        r_upper = r.upper()
        if "US-ONLY" in r_upper or "UNITED STATES" in r_upper or "US ONLY" in r_upper:
            if "US" not in loc and "UNITED STATES" not in loc and "USA" not in loc:
                return False
    return True


def passes_remote_filter(analysis: RemoteAnalysis, prefs: UserPreferences) -> tuple[bool, str]:
    """Returns (passes, reason). Reason is stored for debugging and eval review."""

    if analysis.requires_relocation:
        return False, "requires_relocation"

    if analysis.requires_local_presence:
        return False, "requires_local_presence"

    if analysis.remote_classification in ("onsite_disguised", "hybrid"):
        return False, f"classification:{analysis.remote_classification}"

    if analysis.remote_classification == "remote_with_frequent_travel":
        return False, "travel_too_frequent"

    if analysis.remote_classification == "remote_with_monthly_travel" and prefs.max_travel == "quarterly":
        return False, "travel_more_than_quarterly"

    if analysis.remote_classification == "unclear" and prefs.unclear_routing == "reject":
        return False, "agent_uncertain"

    if analysis.location_restrictions:
        if not _location_compatible(analysis.location_restrictions, prefs.user_location):
            return False, "location_restrictions_mismatch"

    return True, "passed"
