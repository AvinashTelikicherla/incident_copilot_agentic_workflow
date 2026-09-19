"""Repeatable 10-case evaluation harness from the assignment requirements."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from src.runner import run_scenario

CASES = [
    ("db_timeout", ["database connection pool", "DB_TIMEOUT"], "RB-001"),
    ("memory_leak", ["OOMKilled", "memory leak"], "RB-002"),
    ("payment_outage", ["third-party", "Stripe"], "RB-003"),
    ("cache_stampede", ["cache stampede", "invalidation"], "RB-004"),
    ("jwt_rotation", ["JWT", "key rotation"], "RB-005"),
    ("latency_ambiguous", ["CPU throttling", "latency"], "RB-006"),
    ("db_timeout", ["pool exhaustion"], "RB-001"),
    ("payment_outage", ["provider", "circuit breaker"], "RB-003"),
    ("cache_stampede", ["cache miss", "Redis"], "RB-004"),
    ("latency_ambiguous", ["gateway", "CPU"], "RB-006"),
]


def score(outcome: dict, keywords: list[str], expected_runbook: str) -> dict:
    root=outcome.get("likely_root_cause","").lower()
    evidence=json.dumps(outcome.get("evidence",[])).lower()
    diagnosis_pass=any(k.lower() in root for k in keywords)
    context_pass=expected_runbook.lower() in evidence
    action_pass=bool(outcome.get("recommended_actions")) and all(a.get("requires_approval") is True for a in outcome.get("recommended_actions",[]))
    return {"diagnosis_pass":diagnosis_pass,"context_pass":context_pass,"action_pass":action_pass,"latency_ms":outcome.get("total_latency_ms",0)}


def run_config(llm_first: bool) -> list[dict]:
    os.environ["AUTO_APPROVE"]="true"; os.environ["OFFLINE_LLM"]="true"; os.environ["USE_MOCK_SERVICENOW"]="true"; os.environ["LLM_FIRST"]="true" if llm_first else "false"
    rows=[]
    for scenario,keywords,rb in CASES:
        start=time.perf_counter();
        try:
            outcome=run_scenario(scenario,auto_approve=True); elapsed=(time.perf_counter()-start)*1000
            metrics=score(outcome,keywords,rb); metrics["latency_ms"]=round(elapsed,1)
            rows.append({"scenario":scenario,"status":"pass" if metrics["diagnosis_pass"] else "fail",**metrics,"servicenow_created":bool(outcome.get("servicenow_incident")),"method":outcome.get("classification_method")})
        except Exception as exc:
            rows.append({"scenario":scenario,"status":"error","error":str(exc),"diagnosis_pass":False,"context_pass":False,"action_pass":False,"latency_ms":0,"servicenow_created":False,"method":"error"})
    return rows


def summarize(rows: list[dict]) -> dict:
    return {"diagnosis_accuracy":round(sum(r.get("diagnosis_pass",False) for r in rows)/len(rows),3),"context_selection_rate":round(sum(r.get("context_pass",False) for r in rows)/len(rows),3),"action_safety_rate":round(sum(r.get("action_pass",False) for r in rows)/len(rows),3),"servicenow_success_rate":round(sum(r.get("servicenow_created",False) for r in rows)/len(rows),3),"avg_latency_ms":round(sum(r.get("latency_ms",0) for r in rows)/len(rows),1)}


def main():
    deterministic=run_config(False)
    llm_first=run_config(True)
    report={"deterministic_first": {"summary":summarize(deterministic),"cases":deterministic}, "llm_first": {"summary":summarize(llm_first),"cases":llm_first},
            "failure_analysis":["Offline LLM mode is intentionally a repeatable test double, not a model-quality benchmark.","A real evaluation should repeat the 10 cases across model/prompt versions and include token/cost tracking.","Tool failures should route to retry/clarification rather than fabricated evidence."],
            "required_examples":{"clarification":"Both log and metric branches unavailable should route to clarification.","deterministic_rule":"checkout-api DB_TIMEOUT plus pool-waiting signal should be classified before LLM reasoning.","tool_failure":"A retryable ServiceNow timeout should be logged as an action failure and never be replaced with a hallucinated success."}}
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/evaluation_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({"deterministic_first":report["deterministic_first"]["summary"],"llm_first":report["llm_first"]["summary"]},indent=2))

if __name__=="__main__": main()
