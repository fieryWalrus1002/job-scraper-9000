"""Human-facing user config: validated models + transform to pipeline YAML.

The single source of truth for the per-user config format stored in the DB
(specs/configs_in_db_design.md §3). Imported by the API settings endpoints,
the push/pull admin scripts, and (Phase 13) the queue builder.
"""

from .models import (
    LEGACY_REMOTE_CLASSIFICATIONS,
    REMOTE_CLASSIFICATIONS,
    CandidateProfileInput,
    SalaryFloorK,
    SearchConfigInput,
    UserPolicies,
)
from .transform import (
    candidate_profile_to_pipeline_yaml,
    derive_policies,
    dump_yaml,
    search_config_to_pipeline_yaml,
)
from .versioning import canonical_json, compute_profile_version

__all__ = [
    "LEGACY_REMOTE_CLASSIFICATIONS",
    "REMOTE_CLASSIFICATIONS",
    "CandidateProfileInput",
    "SalaryFloorK",
    "SearchConfigInput",
    "UserPolicies",
    "canonical_json",
    "candidate_profile_to_pipeline_yaml",
    "compute_profile_version",
    "derive_policies",
    "dump_yaml",
    "search_config_to_pipeline_yaml",
]
