from pathlib import Path

import pytest
import yaml

from app.rules_engine import detect_budget, detect_urgency, rules_triage
from app.schemas import LeadIn
from app.scoring import load_rules
from conftest import lead_payload


def make_lead(message: str, email: str = "a@acme.example.com", company: str | None = "Acme") -> LeadIn:
    return LeadIn(name="Ana Lopez", email=email, company=company, message=message, source="test")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Budget is $8k to $12k", "explicit"),
        ("We can spend £12,000", "explicit"),
        ("around 20k USD", "explicit"),
        ("not sure about budget yet", "mentioned"),
        ("what does it cost?", "none"),
    ],
)
def test_budget_detection(rules, text, expected):
    assert detect_budget(text.lower(), rules) == expected


@pytest.mark.parametrize(
    "text,expected",
    [("need it asap", "high"), ("decide this quarter", "medium"), ("maybe someday", "low")],
)
def test_urgency_detection(rules, text, expected):
    assert detect_urgency(text, rules) == expected


def test_rules_engine_matches_every_labelled_sample(rules, sample_leads):
    misses = []
    for lead in sample_leads:
        triage, _ = rules_triage(LeadIn(**lead_payload(lead)), rules)
        if triage.category != lead["expected_category"]:
            misses.append((lead["id"], triage.category))
    assert not misses


def test_disposable_email_pushes_towards_spam(rules):
    triage, enrichment = rules_triage(make_lead("hello there", email="x@mailinator.com", company=None), rules)
    assert enrichment["email_type"] == "disposable"
    assert triage.category == "spam"


def test_vague_message_falls_back_to_other(rules):
    triage, _ = rules_triage(make_lead("Please see my website and share thoughts."), rules)
    assert triage.category == "other"


@pytest.mark.parametrize(
    "category,score,expected",
    [
        ("sales_inquiry", 90, "hot"),
        ("sales_inquiry", 75, "hot"),
        ("sales_inquiry", 74, "warm"),
        ("sales_inquiry", 45, "warm"),
        ("sales_inquiry", 44, "cold"),
        ("support", 99, "cold"),
        ("job_seeker", 80, "cold"),
        ("spam", 100, "discard"),
    ],
)
def test_routing_thresholds_and_overrides(rules, category, score, expected):
    assert rules.route(category, score, injection_detected=False) == expected


def test_injection_caps_routing_at_warm(rules):
    assert rules.route("sales_inquiry", 99, injection_detected=True) == "warm"
    assert rules.route("spam", 99, injection_detected=True) == "discard"


def test_client_can_edit_thresholds_in_yaml(tmp_path: Path, settings):
    raw = yaml.safe_load(Path(settings.scoring_rules_path).read_text())
    raw["routing"]["hot_min_score"] = 95
    custom = tmp_path / "rules.yaml"
    custom.write_text(yaml.safe_dump(raw))
    custom_rules = load_rules(custom)
    assert custom_rules.route("sales_inquiry", 90, False) == "warm"


def test_rules_file_missing_section_is_rejected(tmp_path: Path):
    bad = tmp_path / "rules.yaml"
    bad.write_text("version: 1\nrouting: {}\n")
    with pytest.raises(ValueError, match="missing"):
        load_rules(bad)


def test_score_reasons_explain_the_score(rules):
    triage, _ = rules_triage(make_lead("We need a quote, budget $10k, asap."), rules)
    joined = " ".join(triage.score_reasons)
    assert "Budget explicit" in joined and "High urgency" in joined
    assert 0 <= triage.lead_score <= 100
