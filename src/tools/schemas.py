"""MCP-style typed schemas for the AI Incident Copilot."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    SEV1 = "1"
    SEV2 = "2"
    SEV3 = "3"
    SEV4 = "4"


class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"


T = TypeVar("T")


class ToolError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    detail: Optional[Any] = None


class ToolResult(BaseModel, Generic[T]):
    status: ToolStatus
    data: Optional[T] = None
    error: Optional[ToolError] = None
    tool_name: str
    idempotency_key: Optional[str] = None


class SearchRunbooksInput(BaseModel):
    query: str = Field(..., description="Natural-language incident symptoms")
    service: str = Field(..., description="Service name, e.g. checkout-api")
    severity: Severity

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be empty")
        return value.strip()


class RunbookMatch(BaseModel):
    source_id: str
    title: str
    relevance_score: float = Field(ge=0, le=1)
    relevance_reasoning: str
    snippet: str
    remediation_summary: str


class HistoricalIncidentMatch(BaseModel):
    incident_id: str
    title: str
    root_cause: str
    resolution: str
    similarity_score: float = Field(ge=0, le=1)
    key_signals_matched: List[str]


class SearchRunbooksOutput(BaseModel):
    matches: List[RunbookMatch]
    historical_incidents: List[HistoricalIncidentMatch]
    total_found: int


class FetchLogsInput(BaseModel):
    service: str
    start_time: str
    end_time: str
    scenario_hint: Optional[str] = Field(None, description="Simulation hint")

    @field_validator("start_time", "end_time")
    @classmethod
    def valid_iso8601(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid ISO8601 timestamp: {value}") from exc
        return value


class LogEntry(BaseModel):
    timestamp: str
    level: str
    request_id: str
    message: str
    pod: str
    trace_id: str


class FetchLogsOutput(BaseModel):
    service: str
    log_entries: List[LogEntry]
    error_count: int
    warn_count: int
    top_error_messages: List[str]
    time_range: dict


class FetchMetricsInput(BaseModel):
    service: str
    start_time: str
    end_time: str
    scenario_hint: Optional[str] = None


class DependencyHealth(BaseModel):
    name: str
    status: str


class FetchMetricsOutput(BaseModel):
    service: str
    error_rate_pct: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    cpu_utilization_pct: float
    memory_utilization_pct: float
    requests_per_second: float
    dependency_health: List[DependencyHealth]
    recent_deployments: List[dict]
    additional_metrics: dict
    anomaly_signals: List[str]


class CreateServiceNowIncidentInput(BaseModel):
    title: str = Field(..., min_length=5, max_length=160)
    description: str = Field(..., min_length=10)
    severity: Severity
    work_notes: str
    caller_id: str = "incident-copilot"
    idempotency_key: str = Field(..., min_length=8)
    human_approved: bool

    @field_validator("human_approved")
    @classmethod
    def must_be_approved(cls, value: bool) -> bool:
        if not value:
            raise ValueError("create_servicenow_incident requires human_approved=True")
        return value


class CreateServiceNowIncidentOutput(BaseModel):
    incident_number: str
    sys_id: str
    state: str
    url: str
    created_at: str


class UpdateServiceNowIncidentInput(BaseModel):
    incident_id: str
    state: Optional[str] = None
    work_notes: Optional[str] = None
    close_code: Optional[str] = None
    idempotency_key: str = Field(..., min_length=8)
    human_approved: bool

    @field_validator("human_approved")
    @classmethod
    def must_be_approved(cls, value: bool) -> bool:
        if not value:
            raise ValueError("update_servicenow_incident requires human_approved=True")
        return value


class UpdateServiceNowIncidentOutput(BaseModel):
    incident_number: str
    previous_state: str
    new_state: str
    updated_at: str
    url: str


class GetServiceNowIncidentInput(BaseModel):
    incident_id: str


class GetServiceNowIncidentOutput(BaseModel):
    incident_number: str
    title: str
    state: str
    severity: str
    description: str
    work_notes: str
    created_at: str
    updated_at: str
    url: str


MCP_TOOL_REGISTRY = {
    "search_runbooks": {"type": "read", "auth_required": False, "idempotent": True, "input_schema": SearchRunbooksInput.model_json_schema(), "output_schema": SearchRunbooksOutput.model_json_schema()},
    "fetch_logs": {"type": "read", "auth_required": False, "idempotent": True, "input_schema": FetchLogsInput.model_json_schema(), "output_schema": FetchLogsOutput.model_json_schema()},
    "fetch_metrics": {"type": "read", "auth_required": False, "idempotent": True, "input_schema": FetchMetricsInput.model_json_schema(), "output_schema": FetchMetricsOutput.model_json_schema()},
    "create_servicenow_incident": {"type": "write", "auth_required": True, "requires_approval": True, "idempotent": True, "auth_env_vars": ["SNOW_INSTANCE", "SNOW_USERNAME", "SNOW_PASSWORD"], "input_schema": CreateServiceNowIncidentInput.model_json_schema(), "output_schema": CreateServiceNowIncidentOutput.model_json_schema()},
    "update_servicenow_incident": {"type": "write", "auth_required": True, "requires_approval": True, "idempotent": True, "auth_env_vars": ["SNOW_INSTANCE", "SNOW_USERNAME", "SNOW_PASSWORD"], "input_schema": UpdateServiceNowIncidentInput.model_json_schema(), "output_schema": UpdateServiceNowIncidentOutput.model_json_schema()},
    "get_servicenow_incident": {"type": "read", "auth_required": True, "requires_approval": False, "idempotent": True, "auth_env_vars": ["SNOW_INSTANCE", "SNOW_USERNAME", "SNOW_PASSWORD"], "input_schema": GetServiceNowIncidentInput.model_json_schema(), "output_schema": GetServiceNowIncidentOutput.model_json_schema()},
}
