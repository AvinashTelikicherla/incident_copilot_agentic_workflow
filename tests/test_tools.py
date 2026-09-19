from src.tools.context_tools import fetch_logs, fetch_metrics, search_runbooks
from src.tools.schemas import FetchLogsInput, FetchMetricsInput, SearchRunbooksInput, Severity


def test_fetch_logs():
    result=fetch_logs(FetchLogsInput(service="checkout-api",start_time="2026-09-19T16:00:00Z",end_time="2026-09-19T16:10:00Z",scenario_hint="db_timeout_spike"))
    assert result.status.value=="success"
    assert result.data.error_count>=3


def test_metrics_compute_signals():
    result=fetch_metrics(FetchMetricsInput(service="checkout-api",start_time="2026-09-19T16:00:00Z",end_time="2026-09-19T16:10:00Z",scenario_hint="db_timeout_spike"))
    assert "DB_POOL_EXHAUSTED" in result.data.anomaly_signals
    assert "HIGH_ERROR_RATE" in result.data.anomaly_signals


def test_runbook_search():
    result=search_runbooks(SearchRunbooksInput(query="checkout DB_TIMEOUT connection pool",service="checkout-api",severity=Severity.SEV2))
    assert result.status.value=="success"
    assert result.data.matches[0].source_id=="RB-001"
