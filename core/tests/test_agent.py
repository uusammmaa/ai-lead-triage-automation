"""LLM path with a mocked Anthropic SDK: tool loop, retry, fallback, metering."""

from dataclasses import replace

import anthropic
import httpx
from fastapi.testclient import TestClient

from app.agent import TriageAgent
from app.main import create_app
from app.tools import ToolBox
from conftest import FakeAnthropic, final_json, response, text_block, tool_round

LEAD = {
    "name": "Dana Whitfield",
    "email": "dana.whitfield@brightpath-logistics.example.com",
    "company": "Brightpath Logistics",
    "message": "We have a budget of $15,000 and want lead triage within two weeks.",
    "source": "webform",
}


def run(live_settings, headers, script):
    fake = FakeAnthropic(script)
    c = TestClient(create_app(live_settings, client=fake))
    res = c.post("/triage", json=LEAD, headers=headers)
    assert res.status_code == 200
    return res.json(), fake


def test_live_happy_path_runs_tools_then_returns_validated_json(live_settings, headers):
    body, fake = run(live_settings, headers, [tool_round(LEAD["email"]), final_json()])
    assert body["meta"]["mode"] == "live"
    assert body["category"] == "sales_inquiry"
    assert body["routing"] == "hot"  # 88 >= hot_min_score 75, computed by code
    assert body["meta"]["tool_calls"] == ["lookup_scoring_rules", "enrich_email_domain"]
    assert body["meta"]["llm_calls"] == 2
    assert body["meta"]["usage"] == {
        "input_tokens": 3500,
        "output_tokens": 550,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    # Sonnet pricing: 3500 * $2/M + 550 * $10/M
    assert abs(body["meta"]["cost_usd"] - 0.0125) < 1e-9


def test_request_shape_sent_to_claude(live_settings, headers):
    _, fake = run(live_settings, headers, [tool_round(LEAD["email"]), final_json()])
    first, second = fake.calls
    assert first["model"] == "claude-sonnet-5-5"
    assert first["tool_choice"] == {"type": "auto"}
    assert first["output_config"]["format"]["type"] == "json_schema"
    assert {t["name"] for t in first["tools"]} == {"lookup_scoring_rules", "enrich_email_domain"}
    assert all(t["strict"] for t in first["tools"])
    assert first["fallbacks"] == "default"
    # Tool results are returned in a single user message, matched by id.
    results = second["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["tu_1", "tu_2"]
    assert '"email_type": "business"' in results[1]["content"]


def test_model_id_comes_from_env_setting(live_settings, headers):
    _, fake = run(replace(live_settings, anthropic_model="claude-opus-5-5"), headers, [final_json()])
    assert fake.calls[0]["model"] == "claude-opus-5-5"


def test_invalid_output_is_retried_once_then_succeeds(live_settings, headers):
    bad = response([text_block('{"category": "sales_inquiry"}')], "end_turn")
    body, fake = run(live_settings, headers, [bad, final_json()])
    assert body["meta"]["mode"] == "live"
    assert body["meta"]["llm_calls"] == 2
    correction = fake.calls[1]["messages"][-1]["content"]
    assert "failed validation" in correction


def test_two_invalid_outputs_fall_back_to_rules(live_settings, headers):
    bad = response([text_block("not json at all")], "end_turn")
    body, fake = run(live_settings, headers, [bad, bad])
    assert body["meta"]["mode"] == "fallback"
    assert body["meta"]["fallback_reason"].startswith("invalid output")
    assert body["meta"]["llm_calls"] == 2
    assert body["meta"]["cost_usd"] > 0  # failed calls still cost money and are reported
    assert body["category"] == "sales_inquiry"  # rules engine answer


def test_out_of_range_score_counts_as_invalid(live_settings, headers):
    body, _ = run(live_settings, headers, [final_json(lead_score=140), final_json(lead_score=140)])
    assert body["meta"]["mode"] == "fallback"


def test_refusal_falls_back_to_rules(live_settings, headers):
    body, _ = run(live_settings, headers, [response([], "refusal")])
    assert body["meta"]["mode"] == "fallback"
    assert "declined" in body["meta"]["fallback_reason"]


def test_api_outage_falls_back_to_rules(live_settings, headers):
    err = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    body, _ = run(live_settings, headers, [err])
    assert body["meta"]["mode"] == "fallback"
    assert "APIConnectionError" in body["meta"]["fallback_reason"]


def test_code_overrides_model_on_email_facts(live_settings, headers):
    body, _ = run(live_settings, headers, [final_json(company_guess=None)])
    assert body["enrichment"]["email_type"] == "business"
    assert body["enrichment"]["domain"] == "brightpath-logistics.example.com"
    assert body["enrichment"]["company_guess"] == "Brightpath Logistics"


def test_em_dashes_from_model_are_removed(live_settings, headers):
    body, _ = run(live_settings, headers, [final_json(suggested_reply="Hi Dana — great to hear from you.")])
    assert "—" not in body["suggested_reply"]


def test_agent_stops_after_max_steps(rules):
    endless = [tool_round("a@b.example.com") for _ in range(3)]
    agent = TriageAgent(FakeAnthropic(endless), "claude-sonnet-5-5", ToolBox(rules, False), max_steps=3)
    try:
        agent.run(LEAD)
    except Exception as exc:
        assert "did not finish in 3 steps" in str(exc)
    else:
        raise AssertionError("expected AgentError")


def test_server_side_fallback_can_be_disabled(live_settings, headers):
    fake = FakeAnthropic([final_json()])
    TestClient(create_app(replace(live_settings, server_side_fallback=False), client=fake)).post(
        "/triage", json=LEAD, headers=headers
    )
    assert "fallbacks" not in fake.calls[0] and "betas" not in fake.calls[0]
