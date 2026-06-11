"""Human-facing user config: validated models + transform to pipeline YAML.

The single source of truth for the per-user config format stored in the DB
(specs/configs_in_db_design.md §3). Imported by the API settings endpoints,
the push/pull admin scripts, and (Phase 13) the queue builder.
"""

from .models import (
    REMOTE_CLASSIFICATIONS,
    CandidateProfileInput,
    SearchConfigInput,
    UserPolicies,
)
from .transform import (
    candidate_profile_to_pipeline_yaml,
    derive_policies,
    dump_yaml,
    search_config_to_pipeline_yaml,
)

__all__ = [
    "REMOTE_CLASSIFICATIONS",
    "CandidateProfileInput",
    "SearchConfigInput",
    "UserPolicies",
    "candidate_profile_to_pipeline_yaml",
    "derive_policies",
    "dump_yaml",
    "search_config_to_pipeline_yaml",
]
