from dataclasses import replace

from fastapi.testclient import TestClient

from app.main import create_app

LEAD = {"name": "Ana", "email": "ana@acme.example.com", "message": "Need a quote", "source": "test"}


def test_health_is_public(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["mode"] == "mock"


def test_missing_key_is_rejected(client):
    res = client.post("/triage", json=LEAD)
    assert res.status_code == 401


def test_wrong_key_is_rejected(client):
    res = client.post("/triage", json=LEAD, headers={"X-API-Key": "wrong"})
    assert res.status_code == 401


def test_valid_key_is_accepted_and_request_id_echoed(client, headers):
    res = client.post("/triage", json=LEAD, headers={**headers, "X-Request-ID": "abc123"})
    assert res.status_code == 200
    assert res.headers["X-Request-ID"] == "abc123"


def test_auth_disabled_when_no_keys_configured(settings):
    app = create_app(replace(settings, api_keys=[]))
    res = TestClient(app).post("/triage", json=LEAD)
    assert res.status_code == 200


def test_rate_limit_per_key(settings, headers):
    second_key = "other-key-456"
    app = create_app(replace(settings, rate_limit_per_minute=3, api_keys=[headers["X-API-Key"], second_key]))
    c = TestClient(app)
    codes = [c.post("/triage", json=LEAD, headers=headers).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    limited = c.post("/triage", json=LEAD, headers=headers)
    assert int(limited.headers["Retry-After"]) > 0
    # A different key has its own bucket.
    assert c.post("/triage", json=LEAD, headers={"X-API-Key": second_key}).status_code == 200


def test_cors_allows_configured_origin_only(client):
    ok = client.options(
        "/triage",
        headers={"Origin": "http://localhost:8080", "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8080"
    blocked = client.options(
        "/triage",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in blocked.headers
