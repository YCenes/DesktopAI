import asyncio
import socket

import pytest
from fastapi.testclient import TestClient

from nova.api.app import LocalSessionBoundary, create_app
from nova.infrastructure.config import Settings

TOKEN = "b" * 64
SETTINGS = Settings(session_token=TOKEN, port=43210)


@pytest.fixture
def client():
    with TestClient(create_app(SETTINGS), base_url="http://127.0.0.1:43210",
                    headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client


@pytest.mark.parametrize("text,intent,reply", [
    (" 2 + 2 kaç? ", "arithmetic", "Dört."), ("15 çarpı 4", "arithmetic", "Altmış."),
    ("Merhaba", "greeting", None), ("Chrome'u aç", "action_request", None),
    ("Python nedir?", "general_chat", None), ("bilinmeyen", "unknown", None),
    ("I\u0307STANBUL 😀", "unknown", None),
])
def test_authenticated_text_contract(client, text, intent, reply):
    response = client.post("/api/v1/text", json={"text": text})
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"api_version", "original_text", "normalized_text", "intent", "reply", "action", "arithmetic", "external_calls"}
    assert data["original_text"] == text
    assert data["intent"] == intent
    assert data["external_calls"] == 0
    if reply:
        assert data["reply"] == reply
    if data["action"]:
        assert data["action"]["executable"] is False
    assert TOKEN not in response.text


@pytest.mark.parametrize("payload,code", [
    ({"text": ""}, "TEXT_EMPTY"), ({"text": "\t\n"}, "TEXT_EMPTY"),
    ({"text": "a" * 1025}, "TEXT_TOO_LONG"), ({"text": "x\x00y"}, "TEXT_INVALID"),
    ({"text": "\u0344" * 600}, "TEXT_TOO_LONG"),
    ({}, "INVALID_REQUEST"), ({"text": 42}, "INVALID_REQUEST"), ({"text": None}, "INVALID_REQUEST"),
    ({"text": "2+2", "execute": True}, "INVALID_REQUEST"),
    ({"text": "1/0"}, "ARITHMETIC_DIVISION_BY_ZERO"), ({"text": "2**8"}, "ARITHMETIC_INVALID"),
    ({"text": "1000000000000+1"}, "ARITHMETIC_LIMIT"),
])
def test_text_errors_keep_stable_contract(client, payload, code):
    response = client.post("/api/v1/text", json=payload)
    assert response.status_code == 422
    assert set(response.json()) == {"error_code", "message", "request_id"}
    assert response.json()["error_code"] == code
    assert client.get("/api/v1/ready").status_code == 200


def test_text_boundary_and_invalid_json(client):
    assert client.post("/api/v1/text", json={"text": "😀" * 1024}).status_code == 200
    assert client.post("/api/v1/text", content=b"{invalid", headers={"Content-Type": "application/json"}).status_code == 422
    response = client.post("/api/v1/text", content=b"x" * 16_385)
    assert response.status_code == 413
    assert response.json()["error_code"] == "REQUEST_TOO_LARGE"


@pytest.mark.parametrize("headers,status", [({}, 401), ({"Authorization": "Bearer invalid"}, 401),
    ({"Authorization": f"Bearer {TOKEN}", "Host": "evil.example"}, 400),
    ({"Authorization": f"Bearer {TOKEN}", "Origin": "http://evil.example"}, 403)])
def test_text_uses_existing_session_boundary(headers, status):
    with TestClient(create_app(SETTINGS), base_url="http://127.0.0.1:43210") as client:
        assert client.post("/api/v1/text", json={"text": "Chrome'u aç"}, headers=headers).status_code == status


def test_streaming_body_cannot_bypass_byte_limit(client):
    def chunks():
        yield b'{"text":"'
        for _ in range(20):
            yield b"x" * 1024
        yield b'"}'
    assert client.post("/api/v1/text", content=chunks()).status_code == 413


def test_api_all_intents_make_zero_external_requests(client, monkeypatch):
    import httpx
    def forbidden(*args, **kwargs):
        pytest.fail("Metin endpoint'i dış ağ/LLM çağrısı yapamaz")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    for text in ("Merhaba", "2+2", "Chrome'u aç", "Python nedir?", "bilinmeyen"):
        assert client.post("/api/v1/text", json={"text": text}).json()["external_calls"] == 0


@pytest.mark.parametrize("authenticated,expected", [(False, 401), (True, 413)])
def test_asgi_boundary_limits_chunks_before_parsing(authenticated, expected):
    sent = []
    headers = [(b"host", b"127.0.0.1:43210")]
    if authenticated:
        headers.append((b"authorization", f"Bearer {TOKEN}".encode()))
    scope = {"type": "http", "method": "POST", "headers": headers}
    calls = 0

    async def receive():
        nonlocal calls
        calls += 1
        assert authenticated, "Kimlik doğrulanmadan body okunamaz"
        assert calls <= 17, "Aşımda stream okumaya devam edilemez"
        return {"type": "http.request", "body": b"x" * 1024, "more_body": True}

    async def send(message):
        sent.append(message)

    async def forbidden_app(*args):
        pytest.fail("Reddedilecek istek JSON parser'a ulaşamaz")

    asyncio.run(LocalSessionBoundary(forbidden_app, SETTINGS)(scope, receive, send))
    assert sent[0]["status"] == expected
