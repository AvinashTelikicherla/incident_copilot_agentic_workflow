"""Explicit LangGraph workflow with parallel investigation, routing and approval."""
from __future__ import annotations

import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict

try:
    from langgraph.graph import END, StateGraph
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
    END = "__END__"

    class StateGraph:
        """Tiny local compatibility runner used only when LangGraph is unavailable.

        The real package is used automatically when installed. This fallback keeps
        the take-home runnable offline for code review and unit tests.
        """
        def __init__(self, state_type): self.nodes={}; self.entry=None; self.edges={}; self.conditionals={}
        def add_node(self,name,fn): self.nodes[name]=fn
        def set_entry_point(self,name): self.entry=name
        def add_edge(self,a,b): self.edges[a]=b
        def add_conditional_edges(self,a,router,mapping): self.conditionals[a]=(router,mapping)
        def compile(self):
            graph=self
            class Compiled:
                def invoke(self,state):
                    current=graph.entry; guard=0
                    while current != END and guard < 100:
                        guard += 1
                        state=graph.nodes[current](state)
                        if current in graph.conditionals:
                            router,mapping=graph.conditionals[current]; current=mapping[router(state)]
                        else: current=graph.edges.get(current,END)
                    return state
            return Compiled()

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

from src.observability.tracer import log_approval, log_diagnosis, log_run_end, log_run_start, log_tool_call
from src.tools.context_tools import fetch_logs, fetch_metrics, search_runbooks
from src.tools.schemas import CreateServiceNowIncidentInput, FetchLogsInput, FetchMetricsInput, SearchRunbooksInput, Severity, ToolStatus
from src.tools.servicenow_tools import create_servicenow_incident, create_servicenow_incident_mock, make_idempotency_key
from src.workflow.deterministic_classifier import classify_deterministically, needs_llm_reasoning
from src.workflow.state import IncidentCopilotState

_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
_MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE_THRESHOLD", "0.50"))
_USE_MOCK_SNOW = os.getenv("USE_MOCK_SERVICENOW", "true").lower() == "true" or not all(os.getenv(k) for k in ("SNOW_INSTANCE","SNOW_USERNAME","SNOW_PASSWORD"))
_OFFLINE_LLM = os.getenv("OFFLINE_LLM", "false").lower() == "true"
_CLIENT = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", "")) if os.getenv("ANTHROPIC_API_KEY") else None


def node_intake(state: IncidentCopilotState) -> IncidentCopilotState:
    run_id = state.get("run_id") or str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()
    service = state.get("service", "unknown-service")
    severity = state.get("severity", "2")
    log_run_start(run_id, state["incident_description"], service, severity)
    return {**state, "run_id":run_id, "time_window_start":state.get("time_window_start",now), "time_window_end":state.get("time_window_end",now),
            "workflow_status":"running", "retry_count":0, "approval_attempts":0, "logs_retry_count":0, "metrics_retry_count":0,
            "error_trace":[], "llm_reasoning_used":False, "needs_clarification":False}


def node_fetch_logs(state: IncidentCopilotState) -> IncidentCopilotState:
    start=time.perf_counter(); inp=FetchLogsInput(service=state["service"],start_time=state["time_window_start"],end_time=state["time_window_end"],scenario_hint=state.get("scenario_hint")); result=fetch_logs(inp); latency=(time.perf_counter()-start)*1000
    if result.status == ToolStatus.SUCCESS:
        log_tool_call(state["run_id"],"fetch_logs",inp.model_dump(),result.data.model_dump(),latency,"success")
        return {**state,"logs_result":result.data.model_dump(),"logs_error":None}
    err=f"{result.error.code}: {result.error.message}"; log_tool_call(state["run_id"],"fetch_logs",inp.model_dump(),{"error":err},latency,"error")
    return {**state,"logs_result":None,"logs_error":err}


def node_fetch_metrics(state: IncidentCopilotState) -> IncidentCopilotState:
    start=time.perf_counter(); inp=FetchMetricsInput(service=state["service"],start_time=state["time_window_start"],end_time=state["time_window_end"],scenario_hint=state.get("scenario_hint")); result=fetch_metrics(inp); latency=(time.perf_counter()-start)*1000
    if result.status == ToolStatus.SUCCESS:
        log_tool_call(state["run_id"],"fetch_metrics",inp.model_dump(),result.data.model_dump(),latency,"success")
        return {**state,"metrics_result":result.data.model_dump(),"metrics_error":None}
    err=f"{result.error.code}: {result.error.message}"; log_tool_call(state["run_id"],"fetch_metrics",inp.model_dump(),{"error":err},latency,"error")
    return {**state,"metrics_result":None,"metrics_error":err}


def run_parallel_branches(state: IncidentCopilotState) -> IncidentCopilotState:
    """True parallel branch execution; each branch writes to its own state fields."""
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures={executor.submit(node_fetch_logs,state):"logs", executor.submit(node_fetch_metrics,state):"metrics"}
        for future in as_completed(futures):
            branch=futures[future]
            try:
                result=future.result()
                keys=("logs_result","logs_error") if branch=="logs" else ("metrics_result","metrics_error")
                state={**state,**{k:result.get(k) for k in keys}}
            except Exception as exc:
                state={**state,("logs_error" if branch=="logs" else "metrics_error"):str(exc)}
    return state


def node_merge_parallel(state: IncidentCopilotState) -> IncidentCopilotState:
    logs_ok=state.get("logs_result") is not None; metrics_ok=state.get("metrics_result") is not None
    if logs_ok and metrics_ok: status, clarify = "both_ok", False
    elif logs_ok: status, clarify = "logs_only", False
    elif metrics_ok: status, clarify = "metrics_only", False
    else: status, clarify = "both_failed", True
    question=None
    if clarify:
        question=(f"Unable to retrieve logs ({state.get('logs_error')}) or metrics ({state.get('metrics_error')}) for {state['service']}. "
                  "Please provide relevant errors, error rate, and recent deployments.")
    return {**state,"parallel_branch_status":status,"needs_clarification":clarify,"clarification_question":question}


def node_search_runbooks(state: IncidentCopilotState) -> IncidentCopilotState:
    start=time.perf_counter(); parts=[state["incident_description"]]
    if state.get("logs_result"): parts += state["logs_result"].get("top_error_messages",[])[:3]
    inp=SearchRunbooksInput(query=" ".join(parts),service=state["service"],severity=Severity(state.get("severity","2"))); result=search_runbooks(inp); latency=(time.perf_counter()-start)*1000
    if result.status==ToolStatus.SUCCESS:
        log_tool_call(state["run_id"],"search_runbooks",inp.model_dump(),result.data.model_dump(),latency,"success")
        return {**state,"runbook_result":result.data.model_dump(),"runbook_error":None}
    err=f"{result.error.code}: {result.error.message}"; log_tool_call(state["run_id"],"search_runbooks",inp.model_dump(),{"error":err},latency,"error")
    return {**state,"runbook_result":None,"runbook_error":err}


def node_classify_deterministic(state: IncidentCopilotState) -> IncidentCopilotState:
    logs=state.get("logs_result") or {}; metrics=state.get("metrics_result") or {}
    result=classify_deterministically(logs.get("top_error_messages",[]),metrics.get("anomaly_signals",[]),state["service"])
    if result.matched: log_diagnosis(state["run_id"],"deterministic",result.root_cause or "",result.confidence,len(result.evidence))
    return {**state,"deterministic_result":result.__dict__}


def _offline_plan(state: IncidentCopilotState) -> Dict:
    """Repeatable local LLM test double for offline evaluation."""
    m=state.get("metrics_result") or {}; logs=state.get("logs_result") or {}; rb=state.get("runbook_result") or {}
    text=" ".join(logs.get("top_error_messages",[])).lower()
    signals=set(m.get("anomaly_signals",[]))
    if "db_timeout" in text or "db_timeout" in state.get("incident_description","").lower():
        root="Database connection pool exhaustion associated with DB_TIMEOUT errors and saturated pool waiters."; confidence=.91
        action="Verify pool saturation and roll back the recent checkout deployment if the pool configuration changed."
    elif "oomkilled" in text or "outofmemoryerror" in text:
        root="Pod OOMKilled caused by memory growth consistent with a memory leak or insufficient limits."; confidence=.89
        action="Capture heap evidence and roll back the release if the memory growth began with the deployment."
    elif "stripe" in text or "upstream_timeout" in text or "DEPENDENCY_DOWN:stripe-api" in signals:
        root="Third-party payment provider degradation is causing upstream timeouts and circuit-breaker activation."; confidence=.94
        action="Confirm provider health and maintain circuit-breaker protection while monitoring recovery."
    elif "cache" in text or "CACHE_MISS_STORM" in signals:
        root="Cache stampede following broad cache invalidation is driving elevated database load and latency."; confidence=.87
        action="Restore cache warming controls and throttle cache rebuild traffic to protect the database."
    elif "jwt" in text or "signature verification" in text:
        root="JWT signature verification failures are consistent with stale downstream keys after key rotation."; confidence=.93
        action="Refresh downstream JWKS/key caches and validate token verification before restoring traffic."
    elif "cpu throttling" in text or (m.get("p95_latency_ms",0)>2000 and m.get("error_rate_pct",0)<5):
        root="API gateway tail latency is associated with CPU throttling and queueing rather than elevated application errors."; confidence=.74
        action="Inspect gateway CPU throttling and queue depth, then tune capacity or limits."
    else:
        root="Evidence is mixed; additional incident context is required before selecting a remediation."; confidence=.42
        action="Collect more logs, dependency health and recent deployment information."
    evidence=[]
    if logs.get("top_error_messages"): evidence.append({"source":"logs","detail":logs["top_error_messages"][0]})
    if m: evidence.append({"source":"metrics","detail":f"error_rate={m.get('error_rate_pct')}%, p95={m.get('p95_latency_ms')}ms, CPU={m.get('cpu_utilization_pct')}%"})
    if rb.get("matches"): evidence.append({"source":"runbook","detail":f"[{rb['matches'][0]['source_id']}] {rb['matches'][0]['title']}"})
    return {"incident_summary":state["incident_description"][:200],"likely_root_cause":root,"confidence":confidence,"evidence":evidence,
            "recommended_actions":[{"action":action,"risk":"medium","requires_approval":True}],"rollback_plan":"Revert the last configuration/release change if evidence confirms a regression; otherwise monitor the relevant service and dependency metrics.",
            "servicenow_update":{"short_description":f"{state['service']} incident","severity":state.get("severity","2"),"work_notes":f"AI triage summary. Root cause: {root}"}}


def _build_llm_context(state: IncidentCopilotState) -> str:
    parts=[f"Incident: {state['incident_description']}",f"Service: {state['service']} | Severity: {state.get('severity','2')}"]
    if state.get("logs_result"):
        l=state["logs_result"]; parts.append(f"Logs: error_count={l['error_count']}, warn_count={l['warn_count']}, top_errors={l['top_error_messages']}")
    if state.get("metrics_result"):
        m=state["metrics_result"]; parts.append(f"Metrics: error_rate={m['error_rate_pct']}%, p95={m['p95_latency_ms']}ms, CPU={m['cpu_utilization_pct']}%, memory={m['memory_utilization_pct']}%, dependencies={m['dependency_health']}, anomalies={m['anomaly_signals']}")
    if state.get("runbook_result"):
        rb=state["runbook_result"]
        if rb.get("matches"): parts.append(f"Top runbook: {rb['matches'][0]}")
        if rb.get("historical_incidents"): parts.append(f"Historical incident: {rb['historical_incidents'][0]}")
    return "\n".join(parts)


def _parse_json(text: str) -> Dict:
    clean=text.strip()
    if "```json" in clean: clean=clean.split("```json",1)[1].split("```",1)[0].strip()
    elif "```" in clean: clean=clean.split("```",1)[1].split("```",1)[0].strip()
    try: return json.loads(clean)
    except json.JSONDecodeError: return {"incident_summary":"Diagnosis parsing failed","likely_root_cause":clean[:500],"confidence":.3,"evidence":[],"recommended_actions":[],"rollback_plan":"","servicenow_update":{"short_description":"Incident under investigation","severity":state.get("severity","2") if isinstance(state,dict) else "2","work_notes":clean[:1000]}}


def node_llm_diagnose(state: IncidentCopilotState) -> IncidentCopilotState:
    start=time.perf_counter()
    try:
        if _OFFLINE_LLM or _CLIENT is None:
            plan=_offline_plan(state)
        else:
            prompt=("You are an expert SRE Incident Copilot. Produce ONLY valid JSON with keys incident_summary, likely_root_cause, confidence, evidence, recommended_actions, rollback_plan, servicenow_update. Cite concrete logs/metrics/runbook evidence. Any destructive action must require approval.\n\n"+_build_llm_context(state))
            response=_CLIENT.messages.create(model=_MODEL,max_tokens=2000,messages=[{"role":"user","content":prompt}])
            plan=_parse_json(response.content[0].text)
        latency=(time.perf_counter()-start)*1000; needs=plan.get("confidence",0)<_MIN_CONFIDENCE
        log_diagnosis(state["run_id"],"llm",plan.get("likely_root_cause",""),plan.get("confidence",0),len(plan.get("evidence",[])))
        log_tool_call(state["run_id"],"llm_diagnose",{"model":_MODEL,"offline":_OFFLINE_LLM},{"confidence":plan.get("confidence")},latency,"success")
        return {**state,"remediation_plan":plan,"llm_reasoning_used":True,"needs_clarification":needs,"classification_method":"llm"}
    except Exception as exc:
        latency=(time.perf_counter()-start)*1000; log_tool_call(state["run_id"],"llm_diagnose",{}, {"error":str(exc)},latency,"error")
        return {**state,"diagnosis_error":str(exc),"needs_clarification":True,"clarification_question":f"LLM diagnosis failed: {exc}. Please provide additional context."}


def node_build_deterministic_plan(state: IncidentCopilotState) -> IncidentCopilotState:
    det=state.get("deterministic_result") or {}; rb=state.get("runbook_result") or {}; evidence=list(det.get("evidence",[])); recommended=None
    for item in rb.get("matches",[]):
        if item["source_id"]==det.get("recommended_runbook"): recommended=item; break
    if recommended is None and rb.get("matches"): recommended=rb["matches"][0]
    if recommended: evidence.append({"source":"runbook","detail":f"[{recommended['source_id']}] {recommended['relevance_reasoning']}"})
    if rb.get("historical_incidents"): evidence.append({"source":"historical","detail":f"[{rb['historical_incidents'][0]['incident_id']}] Root cause: {rb['historical_incidents'][0]['root_cause']}"})
    root=det.get("root_cause","")
    plan={"incident_summary":state["incident_description"][:200],"likely_root_cause":root,"confidence":det.get("confidence",0),"evidence":evidence,
          "recommended_actions":[{"action":recommended["remediation_summary"] if recommended else "Investigate manually","risk":"medium","requires_approval":True}],
          "rollback_plan":"Refer to the matched runbook rollback steps and monitor error rate/latency after the change.",
          "servicenow_update":{"short_description":f"{state['service']} incident: {det.get('pattern_name','unknown')}","severity":state.get("severity","2"),"work_notes":f"AI Incident Copilot triage. Root cause: {root}. Evidence: {evidence}"}}
    return {**state,"remediation_plan":plan,"classification_method":"deterministic","llm_reasoning_used":False}


def node_human_approval_gate(state: IncidentCopilotState) -> IncidentCopilotState:
    plan=state.get("revised_plan") or state.get("remediation_plan")
    if not plan: return {**state,"human_approved":False,"workflow_status":"failed","human_feedback":"No remediation plan available"}
    auto=os.getenv("AUTO_APPROVE","false").lower()=="true"
    if auto: approved,feedback=True,"Auto-approved (eval/demo mode)"
    else:
        print("\n"+"="*60+"\nAI INCIDENT COPILOT — APPROVAL REQUIRED\n"+"="*60)
        print(json.dumps(plan,indent=2)); response=input("Approve? [y/n] (or feedback): ").strip().lower(); approved=response in ("y","yes","approve",""); feedback="Approved by operator" if approved else response
    attempt=state.get("approval_attempts",0)+1; log_approval(state["run_id"],approved,feedback,attempt)
    return {**state,"human_approved":approved,"human_feedback":feedback,"approval_attempts":attempt,"workflow_status":"approved" if approved else "rejected"}


def node_revise_plan(state: IncidentCopilotState) -> IncidentCopilotState:
    feedback=state.get("human_feedback","")
    if _OFFLINE_LLM or _CLIENT is None:
        revised=dict(state.get("remediation_plan") or {}); revised["recommended_actions"]= [{"action":f"Revise the proposed action based on operator feedback: {feedback}","risk":"medium","requires_approval":True}]; return {**state,"revised_plan":revised,"remediation_plan":revised}
    prompt=_build_llm_context(state)+"\n\nExisting plan:\n"+json.dumps(state.get("remediation_plan"))+f"\n\nOperator rejected with feedback: {feedback}. Return revised JSON only."
    try:
        response=_CLIENT.messages.create(model=_MODEL,max_tokens=1500,messages=[{"role":"user","content":prompt}]); revised=_parse_json(response.content[0].text)
        return {**state,"revised_plan":revised,"remediation_plan":revised}
    except Exception as exc:
        return {**state,"needs_clarification":True,"clarification_question":f"Plan revision failed ({exc}). Please provide additional guidance."}


def node_servicenow_action(state: IncidentCopilotState) -> IncidentCopilotState:
    if not state.get("human_approved"):
        return {**state,"servicenow_error":"ServiceNow action blocked: human approval not granted","workflow_status":"failed"}
    plan=state.get("revised_plan") or state.get("remediation_plan") or {}; update=plan.get("servicenow_update",{})
    key=state.get("snow_idempotency_key") or make_idempotency_key(update.get("short_description",state["incident_description"][:80]),state["service"],state.get("time_window_start",""))
    inp=CreateServiceNowIncidentInput(title=update.get("short_description",state["incident_description"][:80]),description=plan.get("incident_summary",state["incident_description"]),severity=Severity(state.get("severity","2")),work_notes=update.get("work_notes","AI triage complete"),idempotency_key=key,human_approved=True)
    result=(create_servicenow_incident_mock if _USE_MOCK_SNOW else create_servicenow_incident)(inp)
    if result.status==ToolStatus.SUCCESS:
        return {**state,"servicenow_result":result.data.model_dump(),"snow_idempotency_key":key,"servicenow_error":None,"workflow_status":"completed"}
    return {**state,"servicenow_error":f"{result.error.code}: {result.error.message}","workflow_status":"failed"}


def node_clarification(state: IncidentCopilotState) -> IncidentCopilotState:
    q=state.get("clarification_question") or "Please provide more context about the incident."
    if os.getenv("AUTO_APPROVE","false").lower()=="true": response="No additional context available in evaluation mode"
    else: print(f"\nCLARIFICATION NEEDED: {q}"); response=input("Your response: ").strip()
    return {**state,"incident_description":f"{state['incident_description']}\n[Operator clarification: {response}]","needs_clarification":False,"clarification_question":None}


def node_finalize(state: IncidentCopilotState) -> IncidentCopilotState:
    plan=state.get("revised_plan") or state.get("remediation_plan") or {}; snow=state.get("servicenow_result")
    outcome={"run_id":state["run_id"],"service":state["service"],"severity":state.get("severity"),"incident_summary":plan.get("incident_summary",state["incident_description"][:200]),
             "likely_root_cause":plan.get("likely_root_cause","Unknown"),"confidence":plan.get("confidence",0),"classification_method":state.get("classification_method","unknown"),
             "evidence":plan.get("evidence",[]),"recommended_actions":plan.get("recommended_actions",[]),"rollback_plan":plan.get("rollback_plan",""),
             "servicenow_incident":snow.get("incident_number") if snow else None,"servicenow_url":snow.get("url") if snow else None,"workflow_status":state.get("workflow_status"),
             "human_approved":state.get("human_approved"),"llm_used":state.get("llm_reasoning_used",False),"parallel_branch_status":state.get("parallel_branch_status")}
    log_run_end(state["run_id"],state.get("workflow_status","unknown"),outcome,0,snow.get("incident_number") if snow else None)
    return {**state,"final_outcome":outcome}


def route_after_merge(state): return "clarification" if state.get("needs_clarification") else "search_runbooks"
def route_after_classify(state):
    if os.getenv("LLM_FIRST", "false").lower() == "true":
        return "llm_diagnose"
    det=state.get("deterministic_result") or {}
    return "build_deterministic_plan" if det.get("matched") and det.get("confidence",0)>=0.80 and not needs_llm_reasoning(type("R",(),det)()) else "llm_diagnose"
def route_after_plan(state): return "clarification" if state.get("needs_clarification") else "human_approval_gate"
def route_after_approval(state):
    if state.get("human_approved"): return "servicenow_action"
    return "finalize" if state.get("approval_attempts",0)>=3 else "revise_plan"
def route_after_revision(state): return "clarification" if state.get("needs_clarification") else "human_approval_gate"
def route_after_clarification(state): return "search_runbooks"


def build_graph():
    """Build the explicit state machine after investigation branches are populated."""
    builder=StateGraph(IncidentCopilotState)
    for name,fn in [("intake",node_intake),("merge_parallel",node_merge_parallel),("search_runbooks",node_search_runbooks),("classify_deterministic",node_classify_deterministic),
                    ("build_deterministic_plan",node_build_deterministic_plan),("llm_diagnose",node_llm_diagnose),("human_approval_gate",node_human_approval_gate),
                    ("revise_plan",node_revise_plan),("servicenow_action",node_servicenow_action),("clarification",node_clarification),("finalize",node_finalize)]: builder.add_node(name,fn)
    builder.set_entry_point("intake")
    builder.add_edge("intake","merge_parallel")
    builder.add_conditional_edges("merge_parallel",route_after_merge,{"clarification":"clarification","search_runbooks":"search_runbooks"})
    builder.add_edge("search_runbooks","classify_deterministic")
    builder.add_conditional_edges("classify_deterministic",route_after_classify,{"build_deterministic_plan":"build_deterministic_plan","llm_diagnose":"llm_diagnose"})
    for source in ("build_deterministic_plan","llm_diagnose"): builder.add_conditional_edges(source,route_after_plan,{"clarification":"clarification","human_approval_gate":"human_approval_gate"})
    builder.add_conditional_edges("human_approval_gate",route_after_approval,{"servicenow_action":"servicenow_action","revise_plan":"revise_plan","finalize":"finalize"})
    builder.add_conditional_edges("revise_plan",route_after_revision,{"clarification":"clarification","human_approval_gate":"human_approval_gate"})
    builder.add_conditional_edges("clarification",route_after_clarification,{"search_runbooks":"search_runbooks"})
    builder.add_edge("servicenow_action","finalize"); builder.add_edge("finalize",END)
    return builder.compile()
