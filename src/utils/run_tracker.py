"""Per-run telemetry: structured records of every pipeline component run.

Used as a context manager. Captures timing, git provenance, input/output
counts, LLM model/usage, cost estimates, cache stats, and notable events.
Writes append-only to ``data/run_telemetry/runs.jsonl`` by default.

Designed to handle three cases by making the LLM/cost blocks nullable:
  - Cloud LLM (OpenAI): tokens + estimated cost + later actual cost backfill
  - Local LLM (llama.cpp via ollama): tokens (if returned) + zero cost
  - Deterministic (prefilter, scraper): llm=None, cost=None

Reuses ``utils.run_logger.JsonlRunLogger`` for the actual file write, which
handles secret sanitization and run_id-uniqueness checks.
"""

from __future__ import annotations

import logging
import secrets
import statistics
import time
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any

from pydantic import BaseModel, Field

from utils.run_logger import JsonlRunLogger
from utils.git_info import get_git_metadata

log = logging.getLogger(__name__)

DEFAULT_RUNS_PATH = Path("data/run_telemetry/runs.jsonl")


def _iso8601_z(ts: float | None = None) -> str:
    ts = ts if ts is not None else time.time()
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gen_run_id(component: str) -> str:
    return f"{_iso8601_z()}_{component}_{secrets.token_hex(2)}"


# ---- Schema ----


class TimingInfo(BaseModel):
    started_at: str
    ended_at: str | None = None
    duration_seconds: float | None = None


class InputInfo(BaseModel):
    path: str | None = None
    record_count: int = 0
    dedup_dropped: int = 0
    deduped_record_count: int | None = None


class OutputInfo(BaseModel):
    label: str
    path: str | None = None
    record_count: int


class ConfigInfo(BaseModel):
    agent_config_path: str | None = None
    agent_config_hash: str | None = None
    prompt_path: str | None = None
    prompt_hash: str | None = None
    profile_version: str | None = None
    profile_hash: str | None = None


class GitInfo(BaseModel):
    commit: str
    branch: str
    dirty: bool


class LLMInfo(BaseModel):
    provider: str
    model: str
    endpoint: str | None = None
    api_key_env: str | None = None
    temperature: float | None = None
    calls_made: int = 0
    calls_failed: int = 0
    retries_total: int = 0
    input_tokens_total: int | None = None
    input_tokens_cached: int | None = None
    output_tokens_total: int | None = None
    median_latency_seconds: float | None = None
    p95_latency_seconds: float | None = None


class CostBreakdown(BaseModel):
    input_uncached: float | None = None
    input_cached: float | None = None
    output: float | None = None


class CostInfo(BaseModel):
    currency: str = "USD"
    estimated_total: float | None = None
    estimated_per_record: float | None = None
    breakdown: CostBreakdown | None = None
    actual_provider_total: float | None = None
    actual_queried_at: str | None = None
    note: str | None = None


class CacheInfo(BaseModel):
    path: str | None = None
    hits: int = 0
    misses: int = 0
    hit_rate: float | None = None


class EventsInfo(BaseModel):
    rate_limit_events: list[dict[str, Any]] = Field(default_factory=list)
    failure_count: int = 0
    notable: list[str] = Field(default_factory=list)


class LinksInfo(BaseModel):
    parent_run_id: str | None = None
    stdout_log: str | None = None


class RunRecord(BaseModel):
    run_id: str
    component: str
    run_type: str
    run_date: str | None = None

    timing: TimingInfo
    input: InputInfo = Field(default_factory=InputInfo)
    outputs: list[OutputInfo] = Field(default_factory=list)
    config: ConfigInfo = Field(default_factory=ConfigInfo)
    git: GitInfo | None = None
    llm: LLMInfo | None = None
    cost: CostInfo | None = None
    cache: CacheInfo | None = None
    events: EventsInfo = Field(default_factory=EventsInfo)
    links: LinksInfo = Field(default_factory=LinksInfo)
    extras: dict[str, Any] = Field(default_factory=dict)


# ---- Context manager ----


class RunTracker(AbstractContextManager["RunTracker"]):
    """Build a ``RunRecord`` for one component run; write on context exit.

    Usage::

        with RunTracker(component="remote_filter", run_type="production") as run:
            run.set_input(path=..., record_count=...)
            run.set_llm(provider="openai", model="gpt-4o-mini", temperature=0.1)
            # ...do work, capturing per-call usage...
            run.record_call_latency(elapsed_seconds)
            run.add_token_usage(input_tokens=..., cached_input_tokens=..., output_tokens=...)
            run.add_output(label="pass", path=..., record_count=passed)

    On ``__exit__``, derived fields (cache hit_rate, cost.estimated_per_record,
    median/p95 latency) are filled in from accumulated data, then the record is
    written to JSONL. Exceptions are recorded but re-raised.
    """

    def __init__(
        self,
        component: str,
        run_type: str = "production",
        *,
        run_date: str | None = None,
        run_id: str | None = None,
        log_path: str | Path = DEFAULT_RUNS_PATH,
        parent_run_id: str | None = None,
        stdout_log: str | None = None,
        capture_git: bool = True,
    ) -> None:
        self.component = component
        self.run_type = run_type
        self.run_id = run_id or _gen_run_id(component)
        self.log_path = Path(log_path)
        self._writer = JsonlRunLogger(self.log_path)
        self._started_ts: float | None = None
        self._capture_git = capture_git

        self._latencies: list[float] = []
        self._token_totals: dict[str, int] = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
        }

        self.record = RunRecord(
            run_id=self.run_id,
            component=component,
            run_type=run_type,
            run_date=run_date,
            timing=TimingInfo(started_at=""),
            links=LinksInfo(parent_run_id=parent_run_id, stdout_log=stdout_log),
        )

    def __enter__(self) -> "RunTracker":
        self._started_ts = time.time()
        self.record.timing.started_at = _iso8601_z(self._started_ts)
        if self._capture_git:
            try:
                meta = get_git_metadata()
                self.record.git = GitInfo(
                    commit=meta["commit"],
                    branch=meta.get("branch", "unknown"),
                    dirty=meta["dirty"],
                )
            except Exception as exc:
                log.warning("RunTracker: failed to capture git metadata: %s", exc)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        ended_ts = time.time()
        self.record.timing.ended_at = _iso8601_z(ended_ts)
        if self._started_ts is not None:
            self.record.timing.duration_seconds = round(ended_ts - self._started_ts, 3)

        if exc_type is not None:
            self.record.events.failure_count += 1
            self.record.events.notable.append(
                f"run raised {exc_type.__name__}: {exc_val}"
            )

        # Roll up accumulated token counts into the LLM block
        if self.record.llm is not None and any(self._token_totals.values()):
            self.record.llm.input_tokens_total = self._token_totals["input_tokens"]
            self.record.llm.input_tokens_cached = self._token_totals[
                "cached_input_tokens"
            ]
            self.record.llm.output_tokens_total = self._token_totals["output_tokens"]

        # Roll up latencies
        if self.record.llm is not None and self._latencies:
            self.record.llm.median_latency_seconds = round(
                statistics.median(self._latencies), 3
            )
            if len(self._latencies) >= 20:
                k = int(0.95 * len(self._latencies))
                self.record.llm.p95_latency_seconds = round(
                    sorted(self._latencies)[k], 3
                )

        # Derived: cache hit rate
        if (
            self.record.cache
            and (self.record.cache.hits + self.record.cache.misses) > 0
        ):
            total_lookups = self.record.cache.hits + self.record.cache.misses
            self.record.cache.hit_rate = round(
                self.record.cache.hits / total_lookups, 4
            )

        # Derived: cost per record
        if (
            self.record.cost
            and self.record.cost.estimated_total is not None
            and self.record.input.deduped_record_count
        ):
            self.record.cost.estimated_per_record = round(
                self.record.cost.estimated_total
                / self.record.input.deduped_record_count,
                8,
            )

        try:
            self._writer.log_run(self.record.model_dump(exclude_none=False))
        except Exception as exc:
            log.warning("RunTracker: failed to write run record: %s", exc)
        # Do not suppress exceptions
        return None

    # ---- Mutation helpers ----

    def set_input(
        self,
        *,
        path: str | None = None,
        record_count: int = 0,
        dedup_dropped: int = 0,
        deduped_record_count: int | None = None,
    ) -> None:
        self.record.input = InputInfo(
            path=path,
            record_count=record_count,
            dedup_dropped=dedup_dropped,
            deduped_record_count=deduped_record_count,
        )

    def add_output(
        self, *, label: str, path: str | None = None, record_count: int
    ) -> None:
        self.record.outputs.append(
            OutputInfo(label=label, path=path, record_count=record_count)
        )

    def set_config(self, **kwargs: Any) -> None:
        self.record.config = ConfigInfo(**kwargs)

    def set_llm(self, **kwargs: Any) -> None:
        self.record.llm = LLMInfo(**kwargs)

    def update_llm_stats(self, **kwargs: Any) -> None:
        if self.record.llm is None:
            raise ValueError("set_llm() must be called before update_llm_stats()")
        for key, value in kwargs.items():
            setattr(self.record.llm, key, value)

    def set_cost(self, **kwargs: Any) -> None:
        self.record.cost = CostInfo(**kwargs)

    def set_cache(self, **kwargs: Any) -> None:
        self.record.cache = CacheInfo(**kwargs)

    def add_notable(self, msg: str) -> None:
        self.record.events.notable.append(msg)

    def add_rate_limit_event(self, **kwargs: Any) -> None:
        self.record.events.rate_limit_events.append(kwargs)

    def increment_failures(self, n: int = 1) -> None:
        self.record.events.failure_count += n

    def record_call_latency(self, elapsed_seconds: float) -> None:
        self._latencies.append(elapsed_seconds)

    def add_token_usage(
        self,
        usage: dict[str, int] | None = None,
        *,
        input_tokens: int = 0,
        cached_input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Accumulate token counts. Accepts either a dict or kwargs.

        Pass-a-dict form lets you wire this directly as a callback:
            analyze_remote(..., usage_callback=run.add_token_usage)
        """
        if usage is not None:
            input_tokens = usage.get("input_tokens", 0)
            cached_input_tokens = usage.get("cached_input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
        self._token_totals["input_tokens"] += input_tokens
        self._token_totals["cached_input_tokens"] += cached_input_tokens
        self._token_totals["output_tokens"] += output_tokens

    @property
    def token_totals(self) -> dict[str, int]:
        """Read-only view of accumulated token totals."""
        return dict(self._token_totals)
