"""Typed records mirroring persisted rows.

These are plain data carriers (one per table) returned by the repositories.
Timestamps are kept as ISO-8601 strings exactly as stored.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True)


class FeatureSpecRecord(_Row):
    id: int
    feature_name: str
    content_hash: str
    spec_json: str
    segment_field: str | None
    created_at: str
    updated_at: str


class PromptVersionRecord(_Row):
    id: int
    feature_name: str
    version: str
    content_hash: str
    path: str
    content: str
    created_at: str


class DatasetVersionRecord(_Row):
    id: int
    feature_name: str
    version: str
    content_hash: str
    path: str
    case_count: int
    content: str
    created_at: str


class RunRecord(_Row):
    id: int
    run_uuid: str
    feature_name: str
    prompt_version_id: int | None
    dataset_version_id: int | None
    model: str
    judge_enabled: int
    status: str
    git_sha: str | None
    triggered_by: str
    started_at: str
    finished_at: str
    duration_seconds: float
    total_tokens: int
    total_cost_usd: float
    metrics_json: str


class TestResultRecord(_Row):
    id: int
    run_id: int
    case_id: str
    expected_difficulty: str | None
    input_json: str
    expected_json: str
    actual_json: str | None
    passed: int
    scores_json: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    error: str | None


class BaselineRecord(_Row):
    id: int
    feature_name: str
    run_id: int
    is_active: int
    promoted_by: str
    promoted_at: str
    note: str


class RegressionRecord(_Row):
    id: int
    run_id: int
    baseline_run_id: int
    metric: str
    baseline_value: float
    candidate_value: float
    delta: float
    severity: str
    detected_at: str
