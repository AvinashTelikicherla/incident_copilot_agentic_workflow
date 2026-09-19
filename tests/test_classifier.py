from src.workflow.deterministic_classifier import classify_deterministically


def test_db_timeout_rule_beats_llm():
    result=classify_deterministically(["DB_TIMEOUT waiting for connection pool"],["DB_POOL_EXHAUSTED","HIGH_ERROR_RATE"],"checkout-api")
    assert result.matched
    assert result.pattern_name=="db_connection_pool_exhaustion"
    assert result.confidence>=0.9


def test_ambiguous_does_not_match_known_rule():
    result=classify_deterministically(["gateway request latency above p95 threshold"],["HIGH_P95_LATENCY","HIGH_CPU"],"api-gateway")
    assert not result.matched
