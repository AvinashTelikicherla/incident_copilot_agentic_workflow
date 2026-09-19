"""ServiceNow PDI integration with approval and idempotency guards."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

from src.tools.schemas import (
    CreateServiceNowIncidentInput, CreateServiceNowIncidentOutput,
    GetServiceNowIncidentInput, GetServiceNowIncidentOutput,
    ToolError, ToolResult, ToolStatus, UpdateServiceNowIncidentInput,
    UpdateServiceNowIncidentOutput,
)

SNOW_STATE_MAP = {"New":"1", "In Progress":"2", "On Hold":"3", "Resolved":"6", "Closed":"7", "Canceled":"8"}
_MOCK_STORE: dict[str, dict] = {}
_MOCK_BY_KEY: dict[str, str] = {}
_MOCK_COUNTER = 1000000


def _get_snow_config() -> tuple[str, HTTPBasicAuth]:
    instance = os.getenv("SNOW_INSTANCE", "").rstrip("/")
    username = os.getenv("SNOW_USERNAME", "")
    password = os.getenv("SNOW_PASSWORD", "")
    if not all((instance, username, password)):
        raise EnvironmentError("Missing ServiceNow credentials. Set SNOW_INSTANCE, SNOW_USERNAME, SNOW_PASSWORD.")
    return instance, HTTPBasicAuth(username, password)


def _headers() -> dict:
    return {"Content-Type": "application/json", "Accept": "application/json"}


def _error(tool: str, code: str, message: str, retryable: bool = False) -> ToolResult:
    return ToolResult(status=ToolStatus.ERROR, tool_name=tool, error=ToolError(code=code, message=message, retryable=retryable))


def make_idempotency_key(title: str, service: str, time_window: str) -> str:
    raw = f"{title}|{service}|{time_window}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def create_servicenow_incident(inp: CreateServiceNowIncidentInput) -> ToolResult[CreateServiceNowIncidentOutput]:
    if not inp.human_approved:
        return _error("create_servicenow_incident", "APPROVAL_REQUIRED", "Human approval is required before creating a ServiceNow incident.")
    try:
        instance, auth = _get_snow_config()
    except EnvironmentError as exc:
        return _error("create_servicenow_incident", "CONFIG_ERROR", str(exc))
    base_url = f"{instance}/api/now/table/incident"
    try:
        existing = _find_incident_by_idempotency_key(base_url, auth, inp.idempotency_key)
        if existing:
            return ToolResult(status=ToolStatus.SUCCESS, tool_name="create_servicenow_incident", idempotency_key=inp.idempotency_key,
                data=CreateServiceNowIncidentOutput(incident_number=existing["number"], sys_id=existing["sys_id"], state=existing.get("state",""),
                    url=f"{instance}/nav_to.do?uri=incident.do?sys_id={existing['sys_id']}", created_at=existing.get("sys_created_on","")))
    except Exception:
        pass
    payload = {"short_description": inp.title, "description": inp.description, "impact": inp.severity.value,
               "urgency": inp.severity.value, "work_notes": f"[AI Copilot] idempotency_key={inp.idempotency_key}\n\n{inp.work_notes}",
               "caller_id": inp.caller_id, "category":"Software", "subcategory":"Application"}
    try:
        response = requests.post(base_url, auth=auth, headers=_headers(), json=payload, timeout=15)
        response.raise_for_status()
        result = response.json()["result"]
        return ToolResult(status=ToolStatus.SUCCESS, tool_name="create_servicenow_incident", idempotency_key=inp.idempotency_key,
            data=CreateServiceNowIncidentOutput(incident_number=result["number"], sys_id=result["sys_id"], state=result.get("state", {}).get("display_value", "New"),
                url=f"{instance}/nav_to.do?uri=incident.do?sys_id={result['sys_id']}", created_at=result.get("sys_created_on","")))
    except requests.Timeout:
        return _error("create_servicenow_incident", "SNOW_TIMEOUT", "ServiceNow API timed out after 15 seconds", True)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 500
        return _error("create_servicenow_incident", f"SNOW_HTTP_{code}", f"ServiceNow returned HTTP {code}", code in (429,500,502,503))
    except Exception as exc:
        return _error("create_servicenow_incident", "SNOW_UNEXPECTED_ERROR", str(exc), True)


def update_servicenow_incident(inp: UpdateServiceNowIncidentInput) -> ToolResult[UpdateServiceNowIncidentOutput]:
    if not inp.human_approved:
        return _error("update_servicenow_incident", "APPROVAL_REQUIRED", "Human approval is required before updating a ServiceNow incident.")
    try:
        instance, auth = _get_snow_config()
    except EnvironmentError as exc:
        return _error("update_servicenow_incident", "CONFIG_ERROR", str(exc))
    endpoint = f"{instance}/api/now/table/incident"
    try:
        lookup = requests.get(endpoint, auth=auth, headers=_headers(), params={"sysparm_query":f"number={inp.incident_id}","sysparm_fields":"sys_id,state","sysparm_display_value":"true"}, timeout=10)
        lookup.raise_for_status()
        results = lookup.json().get("result", [])
        if not results:
            return _error("update_servicenow_incident", "INCIDENT_NOT_FOUND", f"Incident {inp.incident_id} not found")
        row = results[0]; sys_id = row["sys_id"]
        previous_state = row.get("state", {}).get("display_value", row.get("state", "")) if isinstance(row.get("state"), dict) else row.get("state", "")
        payload = {}
        if inp.state:
            payload["state"] = SNOW_STATE_MAP.get(inp.state, inp.state)
            if inp.state == "Resolved" and inp.close_code:
                payload["close_code"] = inp.close_code
                payload["close_notes"] = inp.work_notes or "Resolved by AI Copilot"
        if inp.work_notes:
            payload["work_notes"] = f"[AI Copilot] idempotency_key={inp.idempotency_key}\n\n{inp.work_notes}"
        patch = requests.patch(f"{endpoint}/{sys_id}", auth=auth, headers=_headers(), json=payload, timeout=15)
        patch.raise_for_status()
        return ToolResult(status=ToolStatus.SUCCESS, tool_name="update_servicenow_incident", idempotency_key=inp.idempotency_key,
            data=UpdateServiceNowIncidentOutput(incident_number=inp.incident_id, previous_state=previous_state, new_state=inp.state or previous_state,
                updated_at=datetime.now(timezone.utc).isoformat(), url=f"{instance}/nav_to.do?uri=incident.do?sys_id={sys_id}"))
    except requests.Timeout:
        return _error("update_servicenow_incident", "SNOW_TIMEOUT", "Timeout updating incident", True)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 500
        return _error("update_servicenow_incident", f"SNOW_HTTP_{code}", "ServiceNow returned an HTTP error", code in (429,500,502,503))
    except Exception as exc:
        return _error("update_servicenow_incident", "SNOW_ERROR", str(exc), True)


def get_servicenow_incident(inp: GetServiceNowIncidentInput) -> ToolResult[GetServiceNowIncidentOutput]:
    try:
        instance, auth = _get_snow_config()
    except EnvironmentError as exc:
        return _error("get_servicenow_incident", "CONFIG_ERROR", str(exc))
    try:
        response = requests.get(f"{instance}/api/now/table/incident", auth=auth, headers=_headers(),
            params={"sysparm_query":f"number={inp.incident_id}","sysparm_display_value":"true"}, timeout=10)
        response.raise_for_status(); results = response.json().get("result", [])
        if not results: return _error("get_servicenow_incident", "INCIDENT_NOT_FOUND", f"Incident {inp.incident_id} not found")
        row = results[0]
        display = lambda key: row.get(key, {}).get("display_value", "") if isinstance(row.get(key), dict) else row.get(key, "")
        return ToolResult(status=ToolStatus.SUCCESS, tool_name="get_servicenow_incident", data=GetServiceNowIncidentOutput(
            incident_number=row.get("number",""), title=row.get("short_description",""), state=display("state"), severity=display("impact"),
            description=row.get("description",""), work_notes=row.get("work_notes",""), created_at=row.get("sys_created_on",""),
            updated_at=row.get("sys_updated_on",""), url=f"{instance}/nav_to.do?uri=incident.do?sys_id={row.get('sys_id','')}"))
    except requests.Timeout:
        return _error("get_servicenow_incident", "SNOW_TIMEOUT", "Timeout reading incident", True)
    except Exception as exc:
        return _error("get_servicenow_incident", "SNOW_ERROR", str(exc), True)


def _find_incident_by_idempotency_key(base_url: str, auth: HTTPBasicAuth, key: str) -> Optional[dict]:
    response = requests.get(base_url, auth=auth, headers=_headers(), params={"sysparm_query":f"work_notesCONTAINS{key}","sysparm_fields":"number,sys_id,state,sys_created_on","sysparm_limit":1}, timeout=10)
    response.raise_for_status(); rows = response.json().get("result", [])
    return rows[0] if rows else None


def create_servicenow_incident_mock(inp: CreateServiceNowIncidentInput) -> ToolResult[CreateServiceNowIncidentOutput]:
    global _MOCK_COUNTER
    if not inp.human_approved: return _error("create_servicenow_incident", "APPROVAL_REQUIRED", "Approval required")
    if inp.idempotency_key in _MOCK_BY_KEY:
        number = _MOCK_BY_KEY[inp.idempotency_key]
        row = _MOCK_STORE[number]
    else:
        _MOCK_COUNTER += 1
        number = f"INC{_MOCK_COUNTER}"
        sys_id = hashlib.sha256(number.encode()).hexdigest()[:32]
        row = {"number":number,"sys_id":sys_id,"title":inp.title,"state":"New","severity":inp.severity.value,"description":inp.description,
               "work_notes":inp.work_notes,"created_at":datetime.now(timezone.utc).isoformat(),"updated_at":datetime.now(timezone.utc).isoformat()}
        _MOCK_STORE[number] = row; _MOCK_BY_KEY[inp.idempotency_key] = number
    return ToolResult(status=ToolStatus.SUCCESS, tool_name="create_servicenow_incident", idempotency_key=inp.idempotency_key,
        data=CreateServiceNowIncidentOutput(incident_number=row["number"],sys_id=row["sys_id"],state=row["state"],url=f"https://mock.service-now.local/{row['number']}",created_at=row["created_at"]))


def update_servicenow_incident_mock(inp: UpdateServiceNowIncidentInput) -> ToolResult[UpdateServiceNowIncidentOutput]:
    if not inp.human_approved: return _error("update_servicenow_incident", "APPROVAL_REQUIRED", "Approval required")
    row = _MOCK_STORE.get(inp.incident_id)
    if not row: return _error("update_servicenow_incident", "INCIDENT_NOT_FOUND", f"Incident {inp.incident_id} not found")
    previous = row["state"]; row["state"] = inp.state or previous
    if inp.work_notes: row["work_notes"] += "\n" + inp.work_notes
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    return ToolResult(status=ToolStatus.SUCCESS, tool_name="update_servicenow_incident", idempotency_key=inp.idempotency_key,
        data=UpdateServiceNowIncidentOutput(incident_number=inp.incident_id,previous_state=previous,new_state=row["state"],updated_at=row["updated_at"],url=f"https://mock.service-now.local/{inp.incident_id}"))


def get_servicenow_incident_mock(inp: GetServiceNowIncidentInput) -> ToolResult[GetServiceNowIncidentOutput]:
    row = _MOCK_STORE.get(inp.incident_id)
    if not row: return _error("get_servicenow_incident", "INCIDENT_NOT_FOUND", f"Incident {inp.incident_id} not found")
    return ToolResult(status=ToolStatus.SUCCESS, tool_name="get_servicenow_incident", data=GetServiceNowIncidentOutput(
        incident_number=row["number"],title=row["title"],state=row["state"],severity=row["severity"],description=row["description"],work_notes=row["work_notes"],
        created_at=row["created_at"],updated_at=row["updated_at"],url=f"https://mock.service-now.local/{row['number']}"))
