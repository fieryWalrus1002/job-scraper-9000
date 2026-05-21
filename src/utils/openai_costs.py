"""Query OpenAI's organization Costs and Usage APIs.

Requires an admin API key (``sk-admin-...``) in env var ``OPENAI_ADMIN_KEY``.
Used by ``scripts/sync_openai_costs.py`` for reconciling estimated run cost
against the provider's authoritative numbers.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

log = logging.getLogger(__name__)

COSTS_URL = "https://api.openai.com/v1/organization/costs"
USAGE_COMPLETIONS_URL = "https://api.openai.com/v1/organization/usage/completions"


def _admin_key() -> str:
    key = os.environ.get("OPENAI_ADMIN_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_ADMIN_KEY is not set; generate a read-only admin key from "
            "the OpenAI dashboard and add it to .env"
        )
    return key


def query_costs(
    start_time: int,
    end_time: int,
    *,
    project_ids: list[str] | None = None,
    group_by: list[str] | None = None,
    bucket_width: str = "1d",
    timeout: float = 30.0,
) -> dict[str, Any]:
    """GET /v1/organization/costs. Only 1d buckets are supported by OpenAI."""
    params: dict[str, Any] = {
        "start_time": start_time,
        "end_time": end_time,
        "bucket_width": bucket_width,
    }
    if project_ids:
        params["project_ids[]"] = project_ids
    if group_by:
        params["group_by[]"] = group_by

    response = requests.get(
        COSTS_URL,
        params=params,
        headers={"Authorization": f"Bearer {_admin_key()}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def query_completions_usage(
    start_time: int,
    end_time: int,
    *,
    project_ids: list[str] | None = None,
    api_key_ids: list[str] | None = None,
    models: list[str] | None = None,
    batch: bool | None = None,
    group_by: list[str] | None = None,
    bucket_width: str = "1h",
    timeout: float = 30.0,
) -> dict[str, Any]:
    """GET /v1/organization/usage/completions. Supports 1m/1h/1d buckets.

    Returns token counts (input, cached, output) and num_model_requests,
    filterable by project, api_key, model, or batch flag.
    """
    params: dict[str, Any] = {
        "start_time": start_time,
        "end_time": end_time,
        "bucket_width": bucket_width,
    }
    if project_ids:
        params["project_ids[]"] = project_ids
    if api_key_ids:
        params["api_key_ids[]"] = api_key_ids
    if models:
        params["models[]"] = models
    if batch is not None:
        params["batch"] = "true" if batch else "false"
    if group_by:
        params["group_by[]"] = group_by

    response = requests.get(
        USAGE_COMPLETIONS_URL,
        params=params,
        headers={"Authorization": f"Bearer {_admin_key()}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def sum_cost_amounts(response: dict[str, Any]) -> float:
    """Sum ``amount.value`` across all results in a Costs API response (USD)."""
    total = 0.0
    for bucket in response.get("data", []):
        for result in bucket.get("results") or []:
            amount = result.get("amount") or {}
            value = amount.get("value")
            if value is not None:
                total += float(value)
    return total
