from unittest.mock import Mock, patch

import pytest

from frontend.utils.api import APIError, SpecBridgeAPI
from frontend.utils.formatting import (
    count_architecture_recommendations,
    engineering_artifacts,
    flatten_assessments,
    markdown_export,
    severity,
    titleize,
)


def test_frontend_formatting_helpers_shape_api_payloads() -> None:
    assert titleize("missing_requirement") == "Missing Requirement"
    assert severity("CRITICAL") == "critical"
    assert flatten_assessments(
        {"assessments": [{"issues": [{"issue_id": "AMB-1"}]}]}
    ) == [{"issue_id": "AMB-1"}]
    assert engineering_artifacts(
        {
            "requirement_blueprints": [
                {"artifacts": [{"artifact_id": "API-1"}]}
            ]
        }
    ) == [{"artifact_id": "API-1"}]
    assert count_architecture_recommendations(
        {"architecture": {"recommendations": [{}, {}]}}
    ) == 2
    assert "# Blueprint" in markdown_export("Blueprint", {"ok": True})


def test_api_client_returns_json() -> None:
    response = Mock(ok=True, status_code=200)
    response.json.return_value = {"status": "ok"}
    with patch("frontend.utils.api.requests.get", return_value=response) as request:
        result = SpecBridgeAPI("http://api.test").get("/health")

    assert result == {"status": "ok"}
    request.assert_called_once_with("http://api.test/health", timeout=120)


def test_api_client_exposes_backend_error_detail() -> None:
    response = Mock(ok=False, status_code=404, text="not found")
    response.json.return_value = {"detail": "Document was not found."}

    with (
        patch("frontend.utils.api.requests.get", return_value=response),
        pytest.raises(APIError, match="Document was not found") as error,
    ):
        SpecBridgeAPI("http://api.test").get("/requirements/example")

    assert error.value.status_code == 404


def test_api_client_wraps_connection_errors() -> None:
    with (
        patch(
            "frontend.utils.api.requests.get",
            side_effect=__import__("requests").ConnectionError("offline"),
        ),
        pytest.raises(APIError, match="Cannot connect to the SpecBridge API"),
    ):
        SpecBridgeAPI("http://api.test").health()
