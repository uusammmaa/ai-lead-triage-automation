"""Run the agent through the real Anthropic SDK against a mock HTTP transport.

No network and no API key: this proves the SDK accepts our request shapes
(system blocks with cache_control, structured output format, strict tools,
beta fallbacks) and that we parse the SDK's real response objects.
"""

import json
from dataclasses import replace

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

LEAD = {
    "name": "Dana Whitfield",
    "email": "dana.whitfield@brightpath-logistics.example.com",
    "company": "Brightpath Logistics",
    "message": "We have a budget of $15,000 and want lead triage within two weeks.",
    "source": "webform",
}
ANSWER = {
    "category": "sales_inquiry",
    "lead_score": 90,
    "score_reasons": ["Explicit budget", "Two week timeline"],
    "urgency": "high",
    "budget_signal": "explicit",
    "summary": "Freight company with a $15k budget wants lead triage within two weeks.",
    "company_guess": "Brightpath Logistics",
    "suggested_reply": "Hi Dana, thanks for reaching out. Could we book a call this week?",
    "confidence": 0.92,
}


def api_message(model: str, content: list, stop_reason: str, cache_read: int = 0) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 400,
            "output_tokens": 120,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": cache_read,
        },
    }


@pytest.fixture
def sdk_app(live_settings):
    requests: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        requests.append({"body": body, "headers": dict(request.headers), "path": request.url.path})
        model = body["model"]
        has_results = any(
            isinstance(m["content"], list) and any(b.get("type") == "tool_result" for b in m["content"])
            for m in body["messages"]
        )
        if not has_results:
            content = [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "tool_use", "id": "toolu_1", "name": "lookup_scoring_rules", "input": {}},
                {"type": "tool_use", "id": "toolu_2", "name": "enrich_email_domain", "input": {"email": LEAD["email"]}},
            ]
            return httpx2.Response(200, json=api_message(model, content, "tool_use"))
        content = [{"type": "text", "text": json.dumps(ANSWER)}]
        return httpx2.Response(200, json=api_message(model, content, "end_turn", cache_read=2600))

    client = anthropic.Anthropic(
        api_key="sk-test",
        base_url="https://api.anthropic.example.com",
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
        max_retries=0,
    )
    settings = replace(live_settings, anthropic_model="claude-haiku-5-5", escalation_model="claude-sonnet-5-5")
    return TestClient(create_app(settings, client=client)), requests


def test_real_sdk_round_trip(sdk_app, headers):
    client, requests = sdk_app
    res = client.post("/triage", json=LEAD, headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["meta"]["mode"] == "live" and body["meta"]["model"] == "claude-haiku-5-5"
    assert body["routing"] == "hot" and body["confidence"] == 0.92
    assert body["meta"]["tool_calls"] == ["lookup_scoring_rules", "enrich_email_domain"]
    assert body["meta"]["usage"]["cache_read_input_tokens"] == 2600
    assert len(requests) == 2 and requests[0]["path"] == "/v1/messages"


def test_wire_format_of_the_haiku_request(sdk_app, headers):
    client, requests = sdk_app
    client.post("/triage", json=LEAD, headers=headers)
    first, second = (r["body"] for r in requests)
    assert first["model"] == "claude-haiku-5-5"
    assert first["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert first["output_config"]["format"]["type"] == "json_schema"
    assert first["output_config"]["effort"] == "low"
    assert all(t["strict"] is True for t in first["tools"])
    for key in ("temperature", "top_p", "top_k", "fallbacks", "thinking"):
        assert key not in first
    assert "anthropic-beta" not in {k.lower() for k in requests[0]["headers"]}
    # The thinking block is passed back unchanged with the tool results.
    assert second["messages"][1]["content"][0]["type"] == "thinking"
    assert second["messages"][2]["content"][0]["type"] == "tool_result"


def test_wire_format_of_the_sonnet_request(live_settings, headers):
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        model = json.loads(request.content)["model"]
        return httpx2.Response(200, json=api_message(model, [{"type": "text", "text": json.dumps(ANSWER)}], "end_turn"))

    client = anthropic.Anthropic(
        api_key="sk-test",
        base_url="https://api.anthropic.example.com",
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
        max_retries=0,
    )
    settings = replace(live_settings, anthropic_model="claude-sonnet-5-5", escalation_model=None)
    res = TestClient(create_app(settings, client=client)).post("/triage", json=LEAD, headers=headers)
    assert res.status_code == 200, res.text
    body = json.loads(seen[0].content)
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in seen[0].headers["anthropic-beta"]
