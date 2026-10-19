"""Cost and quality levers: pre-filter, escalation, prompt caching, few-shots, request params."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.pricing import estimate_cost
from app.rules_engine import prefilter_reason
from app.schemas import LeadIn, Usage
from conftest import FakeAnthropic, final_json, lead_payload, response, text_block, tool_round

HAIKU, SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"
LEAD = {
    "name": "Dana Whitfield",
    "email": "dana.whitfield@brightpath-logistics.example.com",
    "company": "Brightpath Logistics",
    "message": "We have a budget of $15,000 and want lead triage within two weeks.",
    "source": "webform",
}


@pytest.fixture
def haiku_settings(live_settings):
    return replace(live_settings, anthropic_model=HAIKU, escalation_model=SONNET, escalation_threshold=0.6)


def post(settings, headers, script, lead=LEAD):
    fake = FakeAnthropic(script)
    app = create_app(settings, client=fake)
    res = TestClient(app).post("/triage", json=lead, headers=headers)
    assert res.status_code == 200
    return res.json(), fake, app


# ---- Pre-filter ------------------------------------------------------------


def test_disposable_email_is_discarded_without_a_model_call(haiku_settings, headers, sample_leads):
    lead = lead_payload(next(x for x in sample_leads if x["id"] == "L25"))
    body, fake, app = post(haiku_settings, headers, [], lead)  # an empty script fails if the model is called
    assert body["routing"] == "discard"
    assert body["meta"]["mode"] == "prefilter"
    assert body["meta"]["prefilter_reason"] == "disposable_email"
    assert fake.calls == []
    assert app.state.service.stats.snapshot()["model_runs_saved_by_prefilter"] == 1


def test_obvious_spam_from_business_domain_is_prefiltered(haiku_settings, headers, sample_leads):
    lead = lead_payload(next(x for x in sample_leads if x["id"] == "L27"))
    body, fake, _ = post(haiku_settings, headers, [], lead)
    assert body["meta"]["prefilter_reason"] == "spam_keywords"
    assert fake.calls == []


def test_genuine_leads_reach_the_model(haiku_settings, headers):
    body, fake, _ = post(haiku_settings, headers, [tool_round(LEAD["email"]), final_json()])
    assert body["meta"]["mode"] == "live"
    assert len(fake.calls) == 2


def test_prefilter_can_be_turned_off(haiku_settings, headers, sample_leads):
    lead = lead_payload(next(x for x in sample_leads if x["id"] == "L25"))
    body, fake, _ = post(replace(haiku_settings, prefilter=False), headers, [final_json(category="spam")], lead)
    assert body["meta"]["mode"] == "live"
    assert len(fake.calls) == 1


def test_prefilter_never_discards_a_real_lead_in_the_sample(rules, sample_leads):
    flagged = [x for x in sample_leads if prefilter_reason(LeadIn(**lead_payload(x)), rules)]
    assert flagged, "expected the pre-filter to catch some spam"
    assert all(x["expected_routing"] == "discard" for x in flagged)


def test_injection_hidden_in_a_genuine_lead_is_not_prefiltered(rules, sample_leads):
    lead = next(x for x in sample_leads if x["id"] == "L30")
    assert prefilter_reason(LeadIn(**lead_payload(lead)), rules) is None


# ---- Escalation --------------------------------------------------------------


def test_low_confidence_escalates_once_to_the_stronger_model(haiku_settings, headers):
    script = [
        tool_round(LEAD["email"]),
        final_json(confidence=0.4),
        tool_round(LEAD["email"]),
        final_json(confidence=0.9),
    ]
    body, fake, app = post(haiku_settings, headers, script)
    assert [c["model"] for c in fake.calls] == [HAIKU, HAIKU, SONNET, SONNET]
    meta = body["meta"]
    assert meta["escalated"] is True and meta["escalation_reason"] == "low confidence 0.40"
    assert meta["models_used"] == [HAIKU, SONNET]
    assert meta["model"] == SONNET and meta["mode"] == "live"
    assert body["confidence"] == 0.9
    per_call = Usage(input_tokens=1000, output_tokens=200)
    final = Usage(input_tokens=2500, output_tokens=350)
    expected = sum(estimate_cost(m, u) for m in (HAIKU, SONNET) for u in (per_call, final))
    assert meta["cost_usd"] == pytest.approx(expected, abs=1e-6)
    assert app.state.service.stats.snapshot()["escalation_rate"] == 1.0


def test_confident_answers_stay_on_the_cheap_model(haiku_settings, headers):
    body, fake, app = post(haiku_settings, headers, [tool_round(LEAD["email"]), final_json(confidence=0.8)])
    assert [c["model"] for c in fake.calls] == [HAIKU, HAIKU]
    assert body["meta"]["escalated"] is False and body["meta"]["model"] == HAIKU
    assert app.state.service.stats.snapshot()["escalation_rate"] == 0.0


def test_threshold_is_configurable(haiku_settings, headers):
    _, fake, _ = post(
        replace(haiku_settings, escalation_threshold=0.95), headers, [final_json(confidence=0.9), final_json()]
    )
    assert [c["model"] for c in fake.calls] == [HAIKU, SONNET]


def test_two_validation_failures_escalate_instead_of_falling_back(haiku_settings, headers):
    bad = response([text_block("not json")], "end_turn")
    body, fake, _ = post(haiku_settings, headers, [bad, bad, final_json()])
    assert [c["model"] for c in fake.calls] == [HAIKU, HAIKU, SONNET]
    assert body["meta"]["mode"] == "live" and body["meta"]["escalated"] is True
    assert body["meta"]["escalation_reason"].startswith(f"{HAIKU} failed: invalid output")
    assert body["meta"]["llm_calls"] == 3


def test_failed_escalation_keeps_the_valid_low_confidence_answer(haiku_settings, headers):
    bad = response([text_block("not json")], "end_turn")
    body, _, _ = post(haiku_settings, headers, [final_json(confidence=0.3, lead_score=61), bad, bad])
    assert body["meta"]["mode"] == "live"
    assert body["meta"]["model"] == HAIKU and body["lead_score"] == 61


def test_both_models_failing_falls_back_to_rules(haiku_settings, headers):
    bad = response([text_block("not json")], "end_turn")
    body, _, _ = post(haiku_settings, headers, [bad, bad, bad, bad])
    assert body["meta"]["mode"] == "fallback"
    assert body["meta"]["escalated"] is True
    assert body["meta"]["llm_calls"] == 4


def test_escalation_can_be_disabled(haiku_settings, headers):
    body, fake, _ = post(replace(haiku_settings, escalation_model=None), headers, [final_json(confidence=0.2)])
    assert len(fake.calls) == 1 and body["meta"]["escalated"] is False


# ---- Prompt caching, few-shots, request parameters ----------------------------


def test_cache_breakpoint_covers_tools_system_and_examples(haiku_settings, headers):
    _, fake, _ = post(haiku_settings, headers, [final_json()])
    req = fake.calls[0]
    system = req["system"]
    assert len(system) == 2 and "Example 1" in system[1]["text"]
    assert system[-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in system[0]
    assert all("cache_control" not in t for t in req["tools"])
    assert "cache_control" not in req  # no per-lead cache writes of the lead text


def test_caching_and_few_shots_can_be_turned_off(haiku_settings, headers):
    _, fake, _ = post(replace(haiku_settings, prompt_caching=False, few_shot=False), headers, [final_json()])
    system = fake.calls[0]["system"]
    assert len(system) == 1 and "cache_control" not in system[0]


def test_system_prefix_is_identical_across_leads(haiku_settings, headers):
    other = {**LEAD, "email": "someone@else.example.com", "message": "Different lead entirely."}
    _, a, _ = post(haiku_settings, headers, [final_json()])
    _, b, _ = post(haiku_settings, headers, [final_json()], other)
    assert a.calls[0]["system"] == b.calls[0]["system"] and a.calls[0]["tools"] == b.calls[0]["tools"]


def test_tight_max_tokens_and_structured_output(haiku_settings, headers):
    _, fake, _ = post(replace(haiku_settings, max_output_tokens=900), headers, [final_json()])
    req = fake.calls[0]
    assert req["max_tokens"] == 900
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert "confidence" in req["output_config"]["format"]["schema"]["required"]


def test_temperature_is_omitted_by_default_and_for_models_that_reject_it(haiku_settings, headers):
    _, fake, _ = post(haiku_settings, headers, [final_json()])
    assert "temperature" not in fake.calls[0]
    _, fake, _ = post(replace(haiku_settings, temperature=0.0), headers, [final_json()])
    assert "temperature" not in fake.calls[0]  # Haiku 5.5 returns a 400 for non-default temperature


def test_temperature_is_sent_to_models_that_accept_it(haiku_settings, headers):
    s = replace(haiku_settings, anthropic_model="claude-haiku-4-5", escalation_model=None, temperature=0.0)
    _, fake, _ = post(s, headers, [final_json()])
    assert fake.calls[0]["temperature"] == 0.0


def test_server_side_fallback_only_where_supported(haiku_settings, headers):
    script = [final_json(confidence=0.1), final_json()]
    _, fake, _ = post(haiku_settings, headers, script)
    haiku_req, sonnet_req = fake.calls
    assert "fallbacks" not in haiku_req and "betas" not in haiku_req
    assert sonnet_req["fallbacks"] == "default"


def test_health_reports_prefilter_and_escalation_counts(haiku_settings, headers, sample_leads):
    fake = FakeAnthropic([final_json(confidence=0.3), final_json()])
    app = create_app(haiku_settings, client=fake)
    c = TestClient(app)
    c.post("/triage", json=lead_payload(next(x for x in sample_leads if x["id"] == "L25")), headers=headers)
    c.post("/triage", json=LEAD, headers=headers)
    stats = c.get("/health").json()["stats"]
    assert stats["prefiltered_total"] == 1 and stats["escalated_total"] == 1 and stats["escalation_rate"] == 1.0


def test_defaults_are_haiku_with_sonnet_escalation(monkeypatch):
    for var in ("ANTHROPIC_MODEL", "ESCALATION_MODEL", "ESCALATION_CONFIDENCE_THRESHOLD", "TEMPERATURE"):
        monkeypatch.delenv(var, raising=False)
    s = load_settings()
    assert (s.anthropic_model, s.escalation_model, s.escalation_threshold) == (HAIKU, SONNET, 0.6)
    assert s.prompt_caching and s.few_shot and s.prefilter and s.temperature is None
    monkeypatch.setenv("ESCALATION_MODEL", "")
    assert load_settings().escalation_model is None
