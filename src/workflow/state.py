"""Explicit state passed between every workflow node."""
from __future__ import annotations
from typing import Dict, List, Literal, Optional
from typing_extensions import TypedDict


class IncidentCopilotState(TypedDict, total=False):
    run_id: str
    incident_description: str
    service: str
    severity: str
    time_window_start: str
    time_window_end: str
    scenario_hint: Optional[str]
    logs_result: Optional[Dict]
    logs_error: Optional[str]
    logs_retry_count: int
    metrics_result: Optional[Dict]
    metrics_error: Optional[str]
    metrics_retry_count: int
    parallel_branch_status: Optional[Literal["both_ok", "logs_only", "metrics_only", "both_failed"]]
    runbook_result: Optional[Dict]
    runbook_error: Optional[str]
    deterministic_result: Optional[Dict]
    classification_method: Optional[Literal["deterministic", "llm", "hybrid"]]
    remediation_plan: Optional[Dict]
    diagnosis_error: Optional[str]
    llm_reasoning_used: bool
    human_approved: Optional[bool]
    human_feedback: Optional[str]
    approval_attempts: int
    revised_plan: Optional[Dict]
    servicenow_result: Optional[Dict]
    servicenow_error: Optional[str]
    snow_idempotency_key: Optional[str]
    needs_clarification: bool
    clarification_question: Optional[str]
    retry_count: int
    workflow_status: Optional[Literal["running", "awaiting_approval", "approved", "rejected", "completed", "failed", "needs_clarification"]]
    final_outcome: Optional[Dict]
    error_trace: List[str]
