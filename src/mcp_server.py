"""FastMCP exposure for the typed tools.

Local transport is intentionally unauthenticated for the take-home. ServiceNow
credentials remain server-side environment variables and are never tool inputs.
For production HTTP transport, put the server behind authentication and TLS.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv
load_dotenv()

try:
    from fastmcp import FastMCP
except ImportError as exc:
    raise SystemExit("FastMCP is optional. Install requirements.txt to run the MCP server.") from exc

from src.tools.context_tools import fetch_logs, fetch_metrics, search_runbooks
from src.tools.schemas import CreateServiceNowIncidentInput, FetchLogsInput, FetchMetricsInput, GetServiceNowIncidentInput, SearchRunbooksInput, UpdateServiceNowIncidentInput
from src.tools.servicenow_tools import create_servicenow_incident, create_servicenow_incident_mock, get_servicenow_incident, get_servicenow_incident_mock, update_servicenow_incident, update_servicenow_incident_mock

mcp=FastMCP("incident-copilot")
USE_MOCK=os.getenv("USE_MOCK_SERVICENOW","true").lower()=="true"

@mcp.tool()
def search_runbooks_tool(inp: SearchRunbooksInput): return search_runbooks(inp)

@mcp.tool()
def fetch_logs_tool(inp: FetchLogsInput): return fetch_logs(inp)

@mcp.tool()
def fetch_metrics_tool(inp: FetchMetricsInput): return fetch_metrics(inp)

@mcp.tool()
def get_servicenow_incident_tool(inp: GetServiceNowIncidentInput): return get_servicenow_incident_mock(inp) if USE_MOCK else get_servicenow_incident(inp)

@mcp.tool()
def create_servicenow_incident_tool(inp: CreateServiceNowIncidentInput): return create_servicenow_incident_mock(inp) if USE_MOCK else create_servicenow_incident(inp)

@mcp.tool()
def update_servicenow_incident_tool(inp: UpdateServiceNowIncidentInput): return update_servicenow_incident_mock(inp) if USE_MOCK else update_servicenow_incident(inp)

if __name__=="__main__":
    mcp.run()
