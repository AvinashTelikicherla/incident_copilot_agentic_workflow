import pytest
from src.tools.schemas import CreateServiceNowIncidentInput, Severity
from src.tools.servicenow_tools import create_servicenow_incident_mock


def test_write_requires_approval():
    with pytest.raises(ValueError):
        CreateServiceNowIncidentInput(title="test incident",description="test description",severity=Severity.SEV2,work_notes="notes",idempotency_key="abc12345",human_approved=False)


def test_mock_create_is_idempotent():
    inp=CreateServiceNowIncidentInput(title="checkout incident",description="database timeout",severity=Severity.SEV2,work_notes="notes",idempotency_key="same-key-1234",human_approved=True)
    first=create_servicenow_incident_mock(inp); second=create_servicenow_incident_mock(inp)
    assert first.data.incident_number==second.data.incident_number
