# AI Incident Copilot — ServiceNow

A take-home implementation reconstructed from the provided assignment and source-code reference PDFs. The project demonstrates typed tools, explicit LangGraph orchestration, parallel investigation, deterministic-first routing, human approval, ServiceNow PDI integration, MCP/FastMCP exposure, observability and a 10-case evaluation harness.

## What is implemented

- **Typed tools:** Pydantic input/output schemas and structured errors.
- **Parallel investigation:** logs and metrics execute independently and merge with partial-failure handling.
- **Runbook/history retrieval:** deterministic keyword scoring over simulated data.
- **Deterministic vs LLM boundary:** known signatures can bypass LLM reasoning; ambiguous cases use the LLM path.
- **Structured remediation JSON:** diagnosis, confidence, evidence, actions, rollback and ServiceNow update.
- **Human approval:** required before every ServiceNow write; enforced in workflow, schema and function.
- **Idempotency:** stable SHA-256 key prevents duplicate mock/PDI incident creation.
- **ServiceNow PDI:** create/read/update REST functions with credentials from environment variables.
- **MCP:** FastMCP server exposing the six typed tools.
- **Observability:** run/node/tool/diagnosis/approval events with redaction and latency.
- **Evaluation:** ten repeatable cases plus deterministic-first vs LLM-first comparison.

## Project structure

```text
src/
  runner.py
  mcp_server.py
  tools/
    schemas.py
    context_tools.py
    servicenow_tools.py
  workflow/
    state.py
    deterministic_classifier.py
    graph.py
  observability/
    tracer.py
  evaluation/
    harness.py
data/
  logs/service_logs.json
  metrics/service_metrics.json
  runbooks/runbooks.json
  incidents/historical_incidents.json
tests/
docs/
```

## Setup

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env   # Windows
# cp .env.example .env   # Linux/macOS
```

The default `.env.example` is safe for local evaluation: ServiceNow uses the mock adapter and the LLM can be run offline.

## Run demo

List scenarios:

```bash
python -m src.runner --list-scenarios
```

Run a deterministic incident without interactive approval:

```bash
AUTO_APPROVE=true USE_MOCK_SERVICENOW=true python -m src.runner --scenario db_timeout --auto-approve
```

Run the ambiguous LLM path offline:

```bash
AUTO_APPROVE=true USE_MOCK_SERVICENOW=true OFFLINE_LLM=true python -m src.runner --scenario latency_ambiguous --auto-approve
```

For real Anthropic reasoning, set `ANTHROPIC_API_KEY` and `OFFLINE_LLM=false`.

## ServiceNow PDI

Set:

```text
SNOW_INSTANCE=https://<your-pdi>.service-now.com
SNOW_USERNAME=<pdi-user>
SNOW_PASSWORD=<pdi-password>
USE_MOCK_SERVICENOW=false
```

Never commit `.env`. The PDI integration uses the incident table REST API. The write payload includes the idempotency key in work notes, and duplicate creation is checked before POST.

## Approval boundary

A ServiceNow create/update cannot execute unless:

1. the workflow has approved state;
2. the Pydantic write input validates `human_approved=True`;
3. the function performs a second approval check.

`AUTO_APPROVE=true` exists only for controlled demos/evaluation.

## MCP / FastMCP

Start the local server:

```bash
python -m src.mcp_server
```

FastMCP discovers Pydantic schemas and exposes typed tools. Read-only tools are safe to retry. ServiceNow write tools require approval and server-side credentials.

## Evaluation

```bash
AUTO_APPROVE=true OFFLINE_LLM=true USE_MOCK_SERVICENOW=true python -m src.evaluation.harness
```

The harness writes `artifacts/evaluation_report.json` and compares:
- deterministic-first routing;
- LLM-first routing.

The offline LLM is a repeatable test double, not a benchmark of a real model.

## Tests

```bash
pytest -q
```

## Productionization

A production service would be wrapped by FastAPI, containerized, deployed as a Kubernetes Deployment/Service, use Kubernetes Secrets or an external secret manager, expose readiness/liveness endpoints, add distributed tracing and metrics, and use progressive rollout/rollback. Approval should be tied to authenticated users/RBAC rather than a CLI prompt.

## Source reference mapping

The implementation follows the supplied source PDFs:
- Tools layer → `src/tools/schemas.py`, `context_tools.py`, `servicenow_tools.py`.
- Workflow layer → `src/workflow/state.py`, `deterministic_classifier.py`, `graph.py`.
- Entry/evaluation layer → `src/runner.py`, `mcp_server.py`, `observability/tracer.py`, `evaluation/harness.py`.

The original reference contains presentation formatting and a few code-extraction artifacts; this repository normalizes indentation/imports and keeps the described behavior runnable.
