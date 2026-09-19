# Design Note

## Key decisions
1. Use LangGraph for explicit state and conditional routing.
2. Keep context tools read-only and typed with Pydantic models.
3. Run logs and metrics concurrently because they are independent I/O operations.
4. Use deterministic classification before LLM reasoning for known signatures.
5. Require explicit human approval for ServiceNow side effects.
6. Use an idempotency key derived from title/service/time window and store it in work notes.
7. Return structured `ToolResult` envelopes so retryable and non-retryable errors are machine-readable.

## Deterministic vs LLM boundary
Known signatures such as DB_TIMEOUT + pool waiting, OOMKilled + high memory, or JWT verification failure + high error rate are classified before an LLM call. Ambiguous signals such as gateway latency with CPU throttling are sent to the LLM path.

## Safety model
- Credentials come from environment variables.
- Write tools require `human_approved=True`.
- The workflow also checks approval before the write node.
- Duplicate creation is prevented through idempotency.
- Tool failures are surfaced as structured errors.

## Production gaps
The included context sources are simulated JSON. A production deployment would replace them with authenticated log/metric clients and a real vector retrieval layer, add persistent workflow checkpoints, SSO/RBAC for approvals, encrypted secret management, distributed tracing, and automated policy checks.
