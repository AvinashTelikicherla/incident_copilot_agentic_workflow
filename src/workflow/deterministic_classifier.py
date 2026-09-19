"""Deterministic-first incident classifier."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DeterministicResult:
    matched: bool
    root_cause: Optional[str] = None
    confidence: float = 0.0
    evidence: List[dict] = field(default_factory=list)
    recommended_runbook: Optional[str] = None
    method: str = "deterministic"
    pattern_name: Optional[str] = None


RULES = [
    {"name":"db_connection_pool_exhaustion","log_signals":["DB_TIMEOUT","connection pool exhausted","pool exhausted"],"metric_signals":["DB_POOL_EXHAUSTED","HIGH_ERROR_RATE"],"min_log_matches":1,"min_metric_matches":1,"root_cause":"Database connection pool exhaustion. Pool waiting queue > 0 with concurrent DB_TIMEOUT errors indicates connections are saturated.","confidence":0.92,"runbook":"RB-001"},
    {"name":"oom_killed_memory_leak","log_signals":["OOMKilled","OutOfMemoryError","heap space"],"metric_signals":["HIGH_MEMORY","POD_RESTART_LOOP"],"min_log_matches":1,"min_metric_matches":1,"root_cause":"Pod OOMKilled due to memory leak or insufficient memory limits. Memory growth plus repeated restarts indicates unbounded heap usage.","confidence":0.90,"runbook":"RB-002"},
    {"name":"third_party_provider_outage","log_signals":["UPSTREAM_TIMEOUT","circuit breaker","Circuit breaker OPEN"],"metric_signals":["DEPENDENCY_DOWN:stripe-api","HIGH_ERROR_RATE"],"min_log_matches":1,"min_metric_matches":1,"root_cause":"Third-party provider outage or degradation. Upstream timeouts and an open circuit breaker align with dependency failure.","confidence":0.95,"runbook":"RB-003"},
    {"name":"cache_stampede","log_signals":["cache MISS","bulk invalidation","SLAVEOF"],"metric_signals":["CACHE_MISS_STORM"],"min_log_matches":1,"min_metric_matches":1,"root_cause":"Cache stampede following mass cache invalidation. Cache misses are driving a thundering herd toward the database.","confidence":0.88,"runbook":"RB-004"},
    {"name":"jwt_key_rotation_failure","log_signals":["JWT validation failed","signature verification failed"],"metric_signals":["HIGH_ERROR_RATE"],"min_log_matches":2,"min_metric_matches":1,"root_cause":"JWT signature verification failures following key rotation. Downstream services likely retain stale verification keys.","confidence":0.94,"runbook":"RB-005"},
    {"name":"deployment_induced_regression","log_signals":["DB_TIMEOUT","503"],"metric_signals":["RECENT_DEPLOYMENT","HIGH_ERROR_RATE"],"min_log_matches":1,"min_metric_matches":2,"root_cause":"Deployment-induced regression. Errors began after a recent deployment and are consistent with a configuration or code regression.","confidence":0.82,"runbook":"RB-001"},
]


def classify_deterministically(top_error_messages: List[str], anomaly_signals: List[str], service: str) -> DeterministicResult:
    log_text = " ".join(top_error_messages).lower()
    metric_set = set(anomaly_signals)
    best: Optional[DeterministicResult] = None
    for rule in RULES:
        log_hits = sum(sig.lower() in log_text for sig in rule["log_signals"])
        metric_hits = sum(sig in metric_set for sig in rule["metric_signals"])
        if log_hits >= rule["min_log_matches"] and metric_hits >= rule["min_metric_matches"]:
            evidence = [{"source":"logs","detail":f"Log error pattern matched: '{sig}'","type":"deterministic"} for sig in rule["log_signals"] if sig.lower() in log_text]
            evidence += [{"source":"metrics","detail":f"Metric anomaly signal: '{sig}'","type":"deterministic"} for sig in rule["metric_signals"] if sig in metric_set]
            result = DeterministicResult(True, rule["root_cause"], rule["confidence"], evidence, rule["runbook"], "deterministic", rule["name"])
            if best is None or result.confidence > best.confidence: best = result
    return best or DeterministicResult(False)


def needs_llm_reasoning(det_result: DeterministicResult, min_confidence: float = 0.80) -> bool:
    return (not det_result.matched) or det_result.confidence < min_confidence
