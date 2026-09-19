"""CLI entry point for the AI Incident Copilot."""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from src.workflow.graph import build_graph, run_parallel_branches
from src.workflow.state import IncidentCopilotState

SCENARIOS = {
    "db_timeout": {"incident_description":"checkout-api is throwing 5xx errors at 34% rate. DB_TIMEOUT errors seen in logs. Deployment v2.3.1 went out 5 minutes ago.","service":"checkout-api","severity":"2","scenario_hint":"db_timeout_spike"},
    "memory_leak": {"incident_description":"checkout-api pods keep restarting. Memory usage climbing to 91%, OOMKilled events in kubectl describe pod.","service":"checkout-api","severity":"3","scenario_hint":"memory_leak"},
    "payment_outage": {"incident_description":"Payment service has 62% error rate. Stripe API calls timing out at 44 seconds. Circuit breaker is open.","service":"payment-service","severity":"1","scenario_hint":"third_party_timeout"},
    "cache_stampede": {"incident_description":"Inventory service elevated latency and errors after Redis maintenance window. Cache hit rate dropped to near zero.","service":"inventory-service","severity":"2","scenario_hint":"cache_miss_storm"},
    "jwt_rotation": {"incident_description":"Auth service reporting mass 401 errors. JWT signature verification failures. Key rotation was performed at 07:58 UTC.","service":"auth-service","severity":"1","scenario_hint":"jwt_key_rotation"},
    "latency_ambiguous": {"incident_description":"API gateway p95 latency at 3100ms, no obvious root cause. Error rate is low at 2.1%. CPU throttling detected. No recent deployments.","service":"api-gateway","severity":"2","scenario_hint":"high_latency_mixed"},
}


def run_scenario(name: str, auto_approve: bool=False) -> dict:
    if name not in SCENARIOS: raise ValueError(f"Unknown scenario '{name}'")
    if auto_approve: os.environ["AUTO_APPROVE"]="true"
    scenario=SCENARIOS[name]; now=datetime.now(timezone.utc).isoformat(); run_id=str(uuid.uuid4())[:8]
    state: IncidentCopilotState={"run_id":run_id,**scenario,"time_window_start":now,"time_window_end":now}
    print(f"\n{'='*60}\nAI Incident Copilot | Run: {run_id} | Scenario: {name}\n{'='*60}")
    start=time.perf_counter(); state=run_parallel_branches(state); final=build_graph().invoke(state); outcome=final.get("final_outcome",{}); outcome["total_latency_ms"]=round((time.perf_counter()-start)*1000,1)
    print(json.dumps(outcome,indent=2)); return outcome


def interactive_mode():
    print("\nAI Incident Copilot — Interactive Mode")
    desc=input("Incident description: ").strip(); service=input("Service name: ").strip() or "unknown-service"; severity=input("Severity [1-4, default 2]: ").strip() or "2"
    now=datetime.now(timezone.utc).isoformat(); state: IncidentCopilotState={"run_id":str(uuid.uuid4())[:8],"incident_description":desc,"service":service,"severity":severity,"time_window_start":now,"time_window_end":now}
    state=run_parallel_branches(state); final=build_graph().invoke(state); print(json.dumps(final.get("final_outcome",{}),indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description="AI Incident Copilot")
    parser.add_argument("--scenario",choices=list(SCENARIOS),help="Run a predefined scenario")
    parser.add_argument("--auto-approve",action="store_true",help="Auto-approve for demo/evaluation")
    parser.add_argument("--list-scenarios",action="store_true",help="List available scenarios")
    args=parser.parse_args()
    if args.list_scenarios:
        for name,item in SCENARIOS.items(): print(f"{name:20s} — {item['incident_description'][:80]}...")
    elif args.scenario: run_scenario(args.scenario,args.auto_approve)
    else: interactive_mode()
