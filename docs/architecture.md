# Architecture

```mermaid
flowchart TD
    A[Incident intake] --> B[Parallel investigation]
    B --> C1[fetch_logs]
    B --> C2[fetch_metrics]
    C1 --> D[Merge partial evidence]
    C2 --> D
    D --> E[search_runbooks + historical incidents]
    E --> F[Deterministic classifier]
    F -->|Known pattern >= threshold| G[Build structured remediation plan]
    F -->|Unknown / ambiguous| H[LLM diagnosis]
    G --> I[Human approval gate]
    H --> I
    I -->|Rejected| J[Revise / clarify]
    J --> I
    I -->|Approved| K[ServiceNow write]
    K --> L[Finalize + trace]
    I -->|Repeated rejection| L
```

## State and merge strategy
- Logs and metrics are independent branches and write to `logs_result` / `metrics_result`.
- Branch errors are preserved in `logs_error` / `metrics_error`.
- One successful branch is enough to continue with partial evidence.
- If both fail, the workflow asks for clarification.
- ServiceNow writes are blocked unless the approval flag is true at the graph, schema and function layers.
