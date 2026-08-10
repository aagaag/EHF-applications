from __future__ import annotations

import logging

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import ReadinessChecks, create_app


def application() -> TestClient:
    app = create_app(
        Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
        readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
    )

    @app.get("/test-http-error")
    def test_http_error() -> None:
        raise HTTPException(status_code=422, detail="applicant data must not escape")

    @app.get("/test-unhandled-error")
    def test_unhandled_error() -> None:
        raise RuntimeError("server-01 /private/document.pdf token=not-for-output")

    return TestClient(app, base_url="http://localhost", raise_server_exceptions=False)


def test_unknown_routes_have_a_stable_redacted_json_error_envelope() -> None:
    """Break caught: framework defaults could disclose a route or implementation detail."""
    response = application().get("/not-a-route")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Not found",
            "correlation_id": response.headers["x-request-id"],
        }
    }


def test_application_errors_are_redacted_and_keep_the_correlation_id() -> None:
    """Break caught: exception messages could disclose applicant or infrastructure data."""
    client = application()

    handled = client.get("/test-http-error")
    unhandled = client.get("/test-unhandled-error")

    assert handled.status_code == 422
    assert handled.json()["error"] == {
        "code": "invalid_request",
        "message": "Request could not be processed",
        "correlation_id": handled.headers["x-request-id"],
    }
    assert unhandled.status_code == 500
    assert unhandled.json()["error"] == {
        "code": "internal_error",
        "message": "The service could not process this request",
        "correlation_id": unhandled.headers["x-request-id"],
    }
    assert "server-01" not in unhandled.text
    assert "document.pdf" not in unhandled.text
    assert "token=" not in unhandled.text


def test_request_logging_excludes_authorization_cookies_and_bodies(caplog) -> None:
    """Break caught: a diagnostic log could leak credentials or applicant data."""
    caplog.set_level(logging.INFO, logger="ehf.http")
    client = application()

    client.post(
        "/not-a-route",
        content=b"applicant-private-answer",
        headers={
            "Authorization": "Bearer authorization-not-for-logs",
            "Cookie": "session=cookie-not-for-logs",
        },
    )

    output = caplog.text
    assert "authorization-not-for-logs" not in output
    assert "cookie-not-for-logs" not in output
    assert "applicant-private-answer" not in output
    assert "correlation_id=" in output
