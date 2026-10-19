import pytest
from pydantic import ValidationError

from app.schemas import LeadIn, LLMTriage, TriageResponse

VALID = {
    "name": "Dana Whitfield",
    "email": "Dana@Brightpath-Logistics.example.com",
    "company": "Brightpath Logistics",
    "message": "We need lead triage, budget $15k.",
    "source": "webform",
}


def test_lead_normalises_email_and_blank_company():
    lead = LeadIn(**{**VALID, "company": "  "})
    assert lead.email == "dana@brightpath-logistics.example.com"
    assert lead.company is None


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "two@@example.com", "spaces in@example.com"])
def test_lead_rejects_bad_email(email):
    with pytest.raises(ValidationError):
        LeadIn(**{**VALID, "email": email})


def test_lead_requires_message_and_limits_length():
    with pytest.raises(ValidationError):
        LeadIn(**{**VALID, "message": ""})
    with pytest.raises(ValidationError):
        LeadIn(**{**VALID, "message": "x" * 5001})


def test_llm_triage_strips_em_and_en_dashes():
    triage = LLMTriage(
        category="sales_inquiry",
        lead_score=80,
        score_reasons=["Budget \u2014 explicit"],
        urgency="high",
        budget_signal="explicit",
        summary="Big lead \u2014 call today.",
        company_guess=None,
        suggested_reply="Hi Dana \u2014 thanks! Pages 2\u20133 attached.",
    )
    for text in (triage.summary, triage.suggested_reply, *triage.score_reasons):
        assert "\u2014" not in text and "\u2013" not in text


@pytest.mark.parametrize("score", [-1, 101])
def test_llm_triage_rejects_out_of_range_score(score):
    with pytest.raises(ValidationError):
        LLMTriage(
            category="other",
            lead_score=score,
            score_reasons=["x"],
            urgency="low",
            budget_signal="none",
            summary="s",
            company_guess=None,
            suggested_reply="r",
        )


def test_llm_triage_rejects_unknown_category():
    with pytest.raises(ValidationError):
        LLMTriage(
            category="hot_lead",
            lead_score=50,
            score_reasons=["x"],
            urgency="low",
            budget_signal="none",
            summary="s",
            company_guess=None,
            suggested_reply="r",
        )


def test_triage_endpoint_returns_full_contract(client, headers):
    res = client.post("/triage", json=VALID, headers=headers)
    assert res.status_code == 200
    body = TriageResponse.model_validate(res.json())
    assert body.routing in {"hot", "warm", "cold", "discard"}
    assert body.enrichment.domain == "brightpath-logistics.example.com"
    assert body.meta.mode == "mock"
    assert body.lead.email == "dana@brightpath-logistics.example.com"
    assert set(res.json()) >= {
        "category",
        "lead_score",
        "score_reasons",
        "urgency",
        "budget_signal",
        "summary",
        "enrichment",
        "suggested_reply",
        "routing",
    }


def test_triage_endpoint_rejects_invalid_payload(client, headers):
    res = client.post("/triage", json={**VALID, "email": "nope"}, headers=headers)
    assert res.status_code == 422


def test_suggested_replies_never_contain_em_dashes(client, headers, sample_leads):
    from conftest import lead_payload

    for lead in sample_leads:
        body = client.post("/triage", json=lead_payload(lead), headers=headers).json()
        assert "\u2014" not in body["suggested_reply"] + body["summary"]
