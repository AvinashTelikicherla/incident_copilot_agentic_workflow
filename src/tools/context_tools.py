"""Read-only simulated incident investigation tools."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import List

from src.tools.schemas import (
    DependencyHealth, FetchLogsInput, FetchLogsOutput, FetchMetricsInput,
    FetchMetricsOutput, HistoricalIncidentMatch, LogEntry, RunbookMatch,
    SearchRunbooksInput, SearchRunbooksOutput, ToolError, ToolResult, ToolStatus,
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
LOGS_FILE = DATA_DIR / "logs" / "service_logs.json"
METRICS_FILE = DATA_DIR / "metrics" / "service_metrics.json"
RUNBOOKS_FILE = DATA_DIR / "runbooks" / "runbooks.json"
INCIDENTS_FILE = DATA_DIR / "incidents" / "historical_incidents.json"


def _load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def fetch_logs(inp: FetchLogsInput) -> ToolResult[FetchLogsOutput]:
    try:
        all_logs = _load_json(LOGS_FILE)
        service_logs = all_logs.get(inp.service, {})
        if not service_logs:
            return ToolResult(status=ToolStatus.SUCCESS, tool_name="fetch_logs", data=FetchLogsOutput(
                service=inp.service, log_entries=[], error_count=0, warn_count=0,
                top_error_messages=[], time_range={"start": inp.start_time, "end": inp.end_time}))
        scenario = inp.scenario_hint if inp.scenario_hint in service_logs else next(iter(service_logs))
        entries = [LogEntry(**entry) for entry in service_logs[scenario]]
        errors = [e.message for e in entries if e.level == "ERROR"]
        return ToolResult(status=ToolStatus.SUCCESS, tool_name="fetch_logs", data=FetchLogsOutput(
            service=inp.service, log_entries=entries,
            error_count=sum(e.level == "ERROR" for e in entries),
            warn_count=sum(e.level == "WARN" for e in entries),
            top_error_messages=[msg for msg, _ in Counter(errors).most_common(5)],
            time_range={"start": inp.start_time, "end": inp.end_time, "scenario": scenario}))
    except FileNotFoundError:
        return ToolResult(status=ToolStatus.ERROR, tool_name="fetch_logs", error=ToolError(
            code="LOG_FILE_NOT_FOUND", message=f"Log data file not found at {LOGS_FILE}"))
    except Exception as exc:
        return ToolResult(status=ToolStatus.ERROR, tool_name="fetch_logs", error=ToolError(
            code="LOG_FETCH_ERROR", message=str(exc), retryable=True))


def _compute_anomaly_signals(raw: dict) -> List[str]:
    signals: List[str] = []
    if raw.get("error_rate_pct", 0) > 20: signals.append("HIGH_ERROR_RATE")
    if raw.get("p95_latency_ms", 0) > 2000: signals.append("HIGH_P95_LATENCY")
    if raw.get("memory_utilization_pct", 0) > 85: signals.append("HIGH_MEMORY")
    if raw.get("cpu_utilization_pct", 0) > 90: signals.append("HIGH_CPU")
    if raw.get("db_connection_pool_waiting", 0) > 0: signals.append("DB_POOL_EXHAUSTED")
    if raw.get("cache_hit_rate_pct", 100) < 10: signals.append("CACHE_MISS_STORM")
    if raw.get("pod_restart_count", 0) >= 2: signals.append("POD_RESTART_LOOP")
    for dep, status in raw.get("dependency_health", {}).items():
        if status == "DOWN": signals.append(f"DEPENDENCY_DOWN:{dep}")
        elif status == "DEGRADED": signals.append(f"DEPENDENCY_DEGRADED:{dep}")
    if raw.get("recent_deployments"): signals.append("RECENT_DEPLOYMENT")
    return signals


def fetch_metrics(inp: FetchMetricsInput) -> ToolResult[FetchMetricsOutput]:
    try:
        all_metrics = _load_json(METRICS_FILE)
        service_metrics = all_metrics.get(inp.service, {})
        if not service_metrics:
            return ToolResult(status=ToolStatus.ERROR, tool_name="fetch_metrics", error=ToolError(
                code="NO_METRICS_FOR_SERVICE", message=f"No metrics found for service '{inp.service}'"))
        scenario = inp.scenario_hint if inp.scenario_hint in service_metrics else next(iter(service_metrics))
        raw = service_metrics[scenario]
        known = {"error_rate_pct","p50_latency_ms","p95_latency_ms","p99_latency_ms","cpu_utilization_pct","memory_utilization_pct","requests_per_second","dependency_health","recent_deployments"}
        additional = {k: v for k, v in raw.items() if k not in known}
        return ToolResult(status=ToolStatus.SUCCESS, tool_name="fetch_metrics", data=FetchMetricsOutput(
            service=inp.service,
            error_rate_pct=raw.get("error_rate_pct", 0), p50_latency_ms=raw.get("p50_latency_ms", 0),
            p95_latency_ms=raw.get("p95_latency_ms", 0), p99_latency_ms=raw.get("p99_latency_ms", 0),
            cpu_utilization_pct=raw.get("cpu_utilization_pct", 0), memory_utilization_pct=raw.get("memory_utilization_pct", 0),
            requests_per_second=raw.get("requests_per_second", 0),
            dependency_health=[DependencyHealth(name=k, status=v) for k, v in raw.get("dependency_health", {}).items()],
            recent_deployments=raw.get("recent_deployments", []), additional_metrics=additional,
            anomaly_signals=_compute_anomaly_signals(raw)))
    except Exception as exc:
        return ToolResult(status=ToolStatus.ERROR, tool_name="fetch_metrics", error=ToolError(
            code="METRICS_FETCH_ERROR", message=str(exc), retryable=True))


_RUNBOOK_KEYWORD_MAP = {
    "DB_TIMEOUT": ["RB-001"], "connection pool": ["RB-001"], "pool exhausted": ["RB-001"],
    "OOMKilled": ["RB-002"], "memory leak": ["RB-002"], "heap": ["RB-002"], "OutOfMemoryError": ["RB-002"],
    "Stripe": ["RB-003"], "UPSTREAM_TIMEOUT": ["RB-003"], "circuit breaker": ["RB-003"], "payment": ["RB-003"],
    "cache miss": ["RB-004"], "stampede": ["RB-004"], "Redis": ["RB-004"], "cache invalidation": ["RB-004"],
    "JWT": ["RB-005"], "401": ["RB-005"], "signature": ["RB-005"], "key rotation": ["RB-005"],
    "p95 latency": ["RB-006"], "high latency": ["RB-006"], "gateway": ["RB-006"], "upstream degradation": ["RB-006"],
}


def search_runbooks(inp: SearchRunbooksInput) -> ToolResult[SearchRunbooksOutput]:
    try:
        runbooks = _load_json(RUNBOOKS_FILE)
        incidents = _load_json(INCIDENTS_FILE)
        query_lower = inp.query.lower()
        scores: dict[str, float] = {}
        for keyword, ids in _RUNBOOK_KEYWORD_MAP.items():
            if keyword.lower() in query_lower:
                for rb_id in ids: scores[rb_id] = scores.get(rb_id, 0) + 0.25
        for rb in runbooks:
            if rb["service"] in (inp.service, "*"): scores[rb["id"]] = scores.get(rb["id"], 0) + 0.2
            if inp.severity.value in rb.get("severity", []): scores[rb["id"]] = scores.get(rb["id"], 0) + 0.1
        rb_by_id = {rb["id"]: rb for rb in runbooks}
        matches: list[RunbookMatch] = []
        for rb_id, score in sorted(scores.items(), key=lambda x: -x[1]):
            if score < 0.1 or rb_id not in rb_by_id: continue
            rb = rb_by_id[rb_id]
            tags = [t for t in rb.get("tags", []) if t.lower() in query_lower]
            reason = f"Query contains terms matching tags: {', '.join(tags)}" if tags else f"Service '{rb['service']}' matches directly"
            matches.append(RunbookMatch(source_id=rb_id, title=rb["title"], relevance_score=min(score,1), relevance_reasoning=reason,
                snippet=f"Symptom: {rb['symptom_pattern']} | Immediate: {rb['remediation']['immediate']}", remediation_summary=rb["remediation"]["immediate"]))
        historical: list[HistoricalIncidentMatch] = []
        for inc in incidents:
            score = 0.3 if inc["service"] == inp.service else 0
            signals = []
            for signal in inc.get("key_signals", []):
                if signal.lower().replace("_", " ") in query_lower:
                    score += 0.2; signals.append(signal)
            if inc.get("severity") == inp.severity.value: score += 0.1
            if score > 0.2:
                historical.append(HistoricalIncidentMatch(incident_id=inc["id"], title=inc["title"], root_cause=inc["root_cause"], resolution=inc["resolution"], similarity_score=min(score,1), key_signals_matched=signals))
        historical.sort(key=lambda x: -x.similarity_score)
        return ToolResult(status=ToolStatus.SUCCESS, tool_name="search_runbooks", data=SearchRunbooksOutput(
            matches=matches[:5], historical_incidents=historical[:3], total_found=len(matches)+len(historical)))
    except Exception as exc:
        return ToolResult(status=ToolStatus.ERROR, tool_name="search_runbooks", error=ToolError(
            code="RUNBOOK_SEARCH_ERROR", message=str(exc), retryable=True))
