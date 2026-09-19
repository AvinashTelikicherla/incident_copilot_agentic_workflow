# Final Submission Note

## 1. What part is production-ready?
The typed tool contracts, structured error envelopes, approval boundary, idempotency strategy, deterministic classifier, state model, and observability approach are designed as production-oriented components. The ServiceNow REST client is structured for a PDI and keeps credentials outside the tool input.

## 2. What is intentionally mocked?
Logs, metrics, runbooks and historical incidents are local JSON simulations. ServiceNow defaults to an in-memory mock unless PDI credentials are configured. `OFFLINE_LLM=true` uses a repeatable local test double rather than a real model.

## 3. What would improve with one more week?
- Replace keyword retrieval with embeddings/vector search and reranking.
- Add durable LangGraph checkpoints and resumable approvals.
- Add FastAPI + authenticated approval UI/webhook.
- Add real LangSmith/MLflow traces and token/cost metrics.
- Add more failure-injection tests and CI security scanning.
- Run evaluation against multiple real model/prompt configurations.

## 4. Hardest design tradeoff
The central tradeoff is deterministic speed/safety versus LLM flexibility. Known incident signatures should not incur an unnecessary model call, while ambiguous incidents need broader evidence synthesis. The workflow therefore makes deterministic classification the first reasoning boundary and sends only unresolved cases to the LLM.

## 5. Biggest risks in a real SRE deployment
Incorrect remediation, stale retrieval context, excessive permissions, approval bypass, duplicate writes, secret leakage, and insufficient auditability. The implementation addresses these with approval checks, typed tools, idempotency, redaction and explicit evidence, but real deployment would require stronger RBAC, policy enforcement and durable audit storage.

## 6. Where deterministic logic is used and why
The classifier handles DB connection-pool exhaustion, OOM/memory issues, third-party provider failure, cache stampede, JWT key rotation and deployment regression signatures. These are pattern-driven and can be evaluated reproducibly before involving an LLM.

## 7. How to review the Git history
The history is intentionally incremental:

1. scaffold and documentation
2. simulated data
3. typed tools
4. ServiceNow safety/idempotency
5. workflow state/classification
6. parallel LangGraph workflow
7. observability
8. MCP/FastMCP
9. CLI/approval flow
10. evaluation/tests
11. final architecture/evaluation documentation

Each commit has a descriptive message matching the engineering progression requested in the assignment.
