import io
import json

import pytest
from fastapi.testclient import TestClient

from nova.__main__ import read_bootstrap
from nova.api.app import create_app
from nova.infrastructure.config import Settings


TOKEN = "a" * 64  # Yalnızca sentetik test sırrı.
SETTINGS = Settings(session_token=TOKEN, port=43210)
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client():
    with TestClient(create_app(SETTINGS), base_url="http://127.0.0.1:43210", headers=AUTH) as test_client:
        yield test_client


def test_health_and_readiness(client):
    assert client.get("/api/v1/health").json() == {
        "api_version": "1", "app_version": "0.1.0", "status": "ok",
    }
    assert client.get("/api/v1/ready").json() == {"api_version": "1", "status": "ready"}


def test_not_ready_before_lifespan():
    app = create_app(SETTINGS)
    with TestClient(app, base_url="http://127.0.0.1:43210", headers=AUTH) as client:
        app.state.health.ready = False
        response = client.get("/api/v1/ready")
        assert response.status_code == 503
        assert response.json()["error_code"] == "NOT_READY"
    assert app.state.health.ready is False


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}, {"Authorization": ""}])
def test_missing_or_invalid_auth(headers):
    with TestClient(create_app(SETTINGS), base_url="http://127.0.0.1:43210") as client:
        response = client.get("/api/v1/health", headers=headers)
        assert response.status_code == 401
        assert response.json()["error_code"] == "SESSION_UNAUTHORIZED"


@pytest.mark.parametrize("headers,code,status", [
    ({"Host": "evil.example"}, "INVALID_HOST", 400),
    ({"Host": "localhost:43210"}, "INVALID_HOST", 400),
    ({"Origin": "http://evil.example"}, "ORIGIN_FORBIDDEN", 403),
    ({"Origin": "tauri://localhost"}, "ORIGIN_FORBIDDEN", 403),
    ({"Origin": "null"}, "ORIGIN_FORBIDDEN", 403),
])
def test_host_and_origin(client, headers, code, status):
    response = client.get("/api/v1/health", headers=headers)
    assert response.status_code == status
    assert response.json()["error_code"] == code


def test_duplicate_security_headers_rejected(client):
    assert client.get("/api/v1/health", headers=[("Host", SETTINGS.authority), ("Host", SETTINGS.authority)]).status_code == 400
    assert client.get("/api/v1/health", headers=[("Authorization", f"Bearer {TOKEN}"), ("Authorization", f"Bearer {TOKEN}")]).status_code == 401


def test_query_and_errors_are_stable_and_redacted(client):
    for method, path, status, code in [
        ("GET", f"/api/v1/health?token={TOKEN}", 400, "QUERY_FORBIDDEN"),
        ("GET", "/missing", 404, "NOT_FOUND"),
        ("POST", "/api/v1/health", 405, "METHOD_NOT_ALLOWED"),
        ("GET", "/docs", 404, "NOT_FOUND"),
        ("GET", "/openapi.json", 404, "NOT_FOUND"),
    ]:
        response = client.request(method, path)
        assert response.status_code == status
        body = response.json()
        assert set(body) == {"error_code", "message", "request_id"}
        assert body["error_code"] == code
        assert TOKEN not in response.text
        assert body["request_id"]


def test_internal_error_does_not_expose_exception():
    app = create_app(SETTINGS)

    @app.get("/broken")
    def broken():
        raise RuntimeError(TOKEN)

    with TestClient(app, base_url="http://127.0.0.1:43210", headers=AUTH, raise_server_exceptions=False) as client:
        response = client.get("/broken")
        assert response.status_code == 500
        assert response.json()["error_code"] == "INTERNAL_ERROR"
        assert TOKEN not in response.text


def test_validation_error_has_stable_turkish_contract():
    app = create_app(SETTINGS)

    @app.get("/validation/{number}")
    def validation(number: int):
        return {"number": number}

    with TestClient(app, base_url="http://127.0.0.1:43210", headers=AUTH) as client:
        response = client.get("/validation/invalid-number")
        assert response.status_code == 422
        assert response.json()["error_code"] == "INVALID_REQUEST"
        assert response.json()["message"] == "İstek biçimi geçersiz."
        assert "invalid-number" not in response.text


@pytest.mark.parametrize("field,value", [("host", "0.0.0.0"), ("port", 0), ("port", 65536), ("session_token", "short")])
def test_invalid_settings(field, value):
    with pytest.raises(ValueError):
        Settings(**{**dict(session_token=TOKEN, port=43210), field: value})


def test_secret_not_in_config_repr():
    assert TOKEN not in repr(SETTINGS)


@pytest.mark.parametrize("data", [
    "{}\n", "not json\n", "x" * 5000, '{"protocol":2,"token":"x"}\n',
    json.dumps({"protocol": 1, "token": TOKEN, "extra": True}) + "\n",
])
def test_bootstrap_rejects_invalid_contract(data):
    with pytest.raises((ValueError, TypeError)):
        read_bootstrap(io.StringIO(data))


def test_bootstrap_accepts_only_private_pipe_contract():
    assert read_bootstrap(io.StringIO(json.dumps({"protocol": 1, "token": TOKEN}) + "\n")) == TOKEN


def test_openapi_contract_snapshot():
    from pathlib import Path
    expected = json.loads((Path(__file__).parents[3] / "contracts" / "backend.openapi.json").read_text(encoding="utf-8"))
    assert create_app(SETTINGS).openapi() == expected
