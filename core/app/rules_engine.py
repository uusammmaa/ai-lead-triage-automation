"""Deterministic rules classifier.

Used in two places:
- MOCK_MODE, so tests, evals and demos run offline and for free.
- As the safety net when the LLM fails twice or the API is unavailable.

It is deliberately simple and explainable: keyword hits per category, then the
same base scores and modifiers Claude reads from scoring_rules.yaml.
"""

from __future__ import annotations

import re
from typing import Any

from .guard import strip_injection
from .schemas import LeadIn, LLMTriage
from .scoring import ScoringRules
from .tools import enrich_email_domain

# Tie-break order when two categories score the same.
_PRIORITY = ["spam", "job_seeker", "support", "partnership", "sales_inquiry", "other"]

_CURRENCY_RE = re.compile(
    "|".join(
        [
            r"(?:[$\u20ac\u00a3]\s?\d[\d,.]*\s?k?\b)",  # $15,000  \u20ac10k  \u00a312,000
            r"(?:\b\d[\d,.]*\s?k?\s?(?:usd|eur|gbp|dollars|euros|pounds)\b)",  # 20k USD
            r"(?:\bbudget (?:of|is)\s+(?:about |around |approx\.? )?\d[\d,.]*\s?k?\b)",  # budget of 20k
        ]
    ),
    re.IGNORECASE,
)
_GIBBERISH_RE = re.compile(r"\b(?:asdf\w*|qwerty\w*|test(?:\s+test)+|lorem ipsum)\b", re.IGNORECASE)

_BUDGET_TEXT = {"explicit": "an explicit budget", "mentioned": "budget mentioned", "none": "no budget stated"}

_LABELS = {
    "sales_inquiry": "Sales inquiry",
    "support": "Support request",
    "partnership": "Partnership proposal",
    "job_seeker": "Job application",
    "spam": "Likely spam",
    "other": "General enquiry",
}


def _contains(text: str, term: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])", text) is not None


def _hits(text: str, terms: list[str]) -> list[str]:
    return [t for t in terms if _contains(text, str(t))]


def classify_category(text: str, email_type: str, rules: ScoringRules) -> tuple[str, dict[str, list[str]]]:
    scores: dict[str, int] = {}
    matched: dict[str, list[str]] = {}
    for category, spec in rules.raw["keywords"].items():
        hits = _hits(text, spec["terms"])
        matched[category] = hits
        scores[category] = len(hits) * int(spec.get("weight", 1))
    if email_type == "disposable":
        scores["spam"] = scores.get("spam", 0) + 6
    if _GIBBERISH_RE.search(text):
        scores["spam"] = scores.get("spam", 0) + 4
    best = max(scores.values()) if scores else 0
    if best <= 0:
        return "other", matched
    for category in _PRIORITY:
        if scores.get(category, 0) == best:
            return category, matched
    return "other", matched


def detect_urgency(text: str, rules: ScoringRules) -> str:
    if _hits(text, rules.raw["urgency"]["high"]):
        return "high"
    if _hits(text, rules.raw["urgency"]["medium"]):
        return "medium"
    return "low"


def detect_budget(text: str, rules: ScoringRules) -> str:
    if _CURRENCY_RE.search(text):
        return "explicit"
    if _hits(text, rules.raw["budget"]["mentioned_terms"]):
        return "mentioned"
    return "none"


def score_lead(
    category: str,
    email_type: str,
    has_company: bool,
    budget: str,
    urgency: str,
    text: str,
    rules: ScoringRules,
) -> tuple[int, list[str]]:
    scoring = rules.raw["scoring"]
    mods = scoring["modifiers"]
    score = int(scoring["category_base"].get(category, 10))
    reasons = [f"{_LABELS[category]} (base {score})"]
    if category == "spam":
        return 0, reasons + ["Spam signals detected"]

    def add(key: str, reason: str) -> None:
        nonlocal score
        delta = int(mods.get(key, 0))
        if delta:
            score += delta
            reasons.append(f"{reason} ({delta:+d})")

    add(f"{email_type}_email", f"{email_type.capitalize()} email domain")
    if has_company:
        add("company_provided", "Company name provided")
    if budget != "none":
        add(f"budget_{budget}", f"Budget {budget}")
    if urgency in ("high", "medium"):
        add(f"urgency_{urgency}", f"{urgency.capitalize()} urgency timeline")
    signals = rules.raw.get("signals", {})
    if _hits(text, signals.get("crm_or_tool_terms", [])):
        add("crm_or_tool_mentioned", "Mentions CRM or tooling")
    pattern = signals.get("volume_pattern")
    if pattern and re.search(pattern, text, re.IGNORECASE):
        add("volume_mentioned", "Mentions inbound volume")
    return max(0, min(100, score)), reasons[:6]


def _first_name(name: str) -> str:
    first = name.strip().split()[0] if name.strip() else "there"
    return first if first.isalpha() else "there"


def _reply(category: str, lead: LeadIn, rules: ScoringRules) -> str:
    first = _first_name(lead.name)
    reply_cfg = rules.raw["reply"]
    sign = reply_cfg.get("sender_name", "The team")
    templates = {
        "sales_inquiry": (
            f"Hi {first}, thanks for reaching out. This sounds like a good fit for what we do. "
            f"Could we book a 20 minute call to go through your goals and timeline? "
            f"You can pick a slot here: {reply_cfg.get('booking_link', '')}. Best regards, {sign}"
        ),
        "partnership": (
            f"Hi {first}, thanks for thinking of us. We are open to the right partnerships. "
            f"Could you share a short overview of what you have in mind and who your clients are? "
            f"We will review it and come back to you this week. Best regards, {sign}"
        ),
        "support": (
            f"Hi {first}, thanks for letting us know and sorry for the trouble. "
            f"I have passed this to our support team and someone will follow up shortly. "
            f"Any screenshots or error messages will help us fix it faster. Best regards, {sign}"
        ),
        "job_seeker": (
            f"Hi {first}, thanks for your interest in working with us. We do not have an open role "
            f"that matches right now, but we will keep your details on file and reach out if that "
            f"changes. Best regards, {sign}"
        ),
        "other": (
            f"Hi {first}, thanks for getting in touch. Could you tell us a little more about what "
            f"you are looking for, so we can point you in the right direction? Best regards, {sign}"
        ),
        "spam": "No reply recommended.",
    }
    return templates[category]


def _summary(category: str, lead: LeadIn, matched: dict[str, list[str]], urgency: str, budget: str) -> str:
    who = lead.name + (f" ({lead.company})" if lead.company else "")
    topics = matched.get(category, [])[:3]
    about = f" mentioning {', '.join(topics)}" if topics else ""
    budget_text = _BUDGET_TEXT[budget]
    return f"{_LABELS[category]} from {who}{about}, with {urgency} urgency and {budget_text}."


def rules_triage(lead: LeadIn, rules: ScoringRules) -> tuple[LLMTriage, dict[str, Any]]:
    """Classify a lead with rules only. Returns the triage and the enrichment dict."""
    enrichment = enrich_email_domain(lead.email, rules)
    raw_text = f"{lead.company or ''}\n{lead.message}"
    text = strip_injection(raw_text).lower()
    category, matched = classify_category(text, enrichment["email_type"], rules)
    urgency = detect_urgency(text, rules) if category != "spam" else "low"
    budget = detect_budget(text, rules) if category in ("sales_inquiry", "partnership", "other") else "none"
    score, reasons = score_lead(category, enrichment["email_type"], bool(lead.company), budget, urgency, text, rules)
    triage = LLMTriage(
        category=category,
        lead_score=score,
        score_reasons=reasons,
        urgency=urgency,
        budget_signal=budget,
        summary=_summary(category, lead, matched, urgency, budget),
        company_guess=lead.company or enrichment["company_guess"],
        suggested_reply=_reply(category, lead, rules),
    )
    return triage, enrichment
