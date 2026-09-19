"""Lightweight structured observability; sensitive values are redacted."""
from __future__ import annotations
import json
import logging
import os
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("incident-copilot")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "[REDACTED]" if any(x in k.lower() for x in ("password","secret","token","api_key")) else _redact(v) for k,v in value.items()}
    if isinstance(value, list): return [_redact(v) for v in value]
    return value


def emit(event: str, **payload: Any) -> None:
    logger.info(json.dumps({"timestamp":datetime.now(timezone.utc).isoformat(),"event":event,**_redact(payload)}, default=str))


def log_run_start(run_id: str, incident_description: str, service: str, severity: str) -> None:
    emit("run_start", run_id=run_id, incident_description=incident_description[:300], service=service, severity=severity)


def log_tool_call(run_id: str, tool_name: str, inputs: Any, outputs: Any, latency_ms: float, status: str) -> None:
    emit("tool_call", run_id=run_id, tool_name=tool_name, inputs=inputs, outputs=outputs, latency_ms=round(latency_ms,2), status=status)


def log_diagnosis(run_id: str, method: str, root_cause: str, confidence: float, evidence_count: int) -> None:
    emit("diagnosis", run_id=run_id, method=method, root_cause=root_cause[:300], confidence=confidence, evidence_count=evidence_count)


def log_approval(run_id: str, approved: bool, feedback: str, attempt: int) -> None:
    emit("approval", run_id=run_id, approved=approved, feedback=feedback[:300], attempt=attempt)


def log_run_end(run_id: str, status: str, final_outcome: dict, total_latency_ms: float, incident_id: str | None) -> None:
    emit("run_end", run_id=run_id, status=status, final_outcome=final_outcome, total_latency_ms=total_latency_ms, incident_id=incident_id)


def timed_node(name: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start=time.perf_counter(); result=func(*args, **kwargs); elapsed=(time.perf_counter()-start)*1000
            state=result if isinstance(result, dict) else {}
            emit("node_execution", node=name, run_id=state.get("run_id"), latency_ms=round(elapsed,2))
            return result
        return wrapper
    return decorator
