"""Request and response models for the triage API.

Everything that leaves the service passes through these models, so a bad LLM
response can never reach a CRM row, a Slack channel or a Gmail draft.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Category = Literal["sales_inquiry", "support", "partnership", "job_seeker", "spam", "other"]
Urgency = Literal["low", "medium", "high"]
BudgetSignal = Literal["none", "mentioned", "explicit"]
EmailType = Literal["business", "free", "disposable"]
Routing = Literal["hot", "warm", "cold", "discard"]
Mode = Literal["live", "mock", "fallback"]

CATEGORIES: tuple[str, ...] = ("sales_inquiry", "support", "partnership", "job_seeker", "spam", "other")

EM_DASH, EN_DASH = chr(0x2014), chr(0x2013)
_EMAIL_RE = re.compile(
    r"^[^@\s]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


def strip_dashes(text: str) -> str:
    """House style: no em or en dashes in anything a client or lead reads."""
    return text.replace(f" {EM_DASH} ", ", ").replace(EM_DASH, ", ").replace(EN_DASH, "-")


class LeadIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=254)
    company: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=1, max_length=5000)
    source: str = Field(default="webform", min_length=1, max_length=50)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        if not _EMAIL_RE.match(value):
            raise ValueError("email is not a valid address")
        return value.lower()

    @field_validator("company")
    @classmethod
    def _blank_company_is_none(cls, value: str | None) -> str | None:
        return value or None


class Enrichment(BaseModel):
    email_type: EmailType
    domain: str
    company_guess: str | None = None


class LLMTriage(BaseModel):
    """What the model is asked to produce. Routing and email facts are added by code."""

    category: Category
    lead_score: int = Field(ge=0, le=100)
    score_reasons: list[str] = Field(min_length=1, max_length=6)
    urgency: Urgency
    budget_signal: BudgetSignal
    summary: str = Field(min_length=1, max_length=300)
    company_guess: str | None = Field(default=None, max_length=120)
    suggested_reply: str = Field(min_length=1, max_length=1200)

    @field_validator("summary", "suggested_reply")
    @classmethod
    def _no_dashes(cls, value: str) -> str:
        return strip_dashes(value).strip()

    @field_validator("score_reasons")
    @classmethod
    def _clean_reasons(cls, value: list[str]) -> list[str]:
        cleaned = [strip_dashes(r).strip()[:160] for r in value if r and r.strip()]
        if not cleaned:
            raise ValueError("score_reasons must contain at least one non-empty reason")
        return cleaned


class TriageResult(BaseModel):
    category: Category
    lead_score: int = Field(ge=0, le=100)
    score_reasons: list[str]
    urgency: Urgency
    budget_signal: BudgetSignal
    summary: str
    enrichment: Enrichment
    suggested_reply: str
    routing: Routing


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class TriageMeta(BaseModel):
    lead_id: str
    mode: Mode
    model: str | None = None
    latency_ms: int
    llm_calls: int = 0
    tool_calls: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    injection_detected: bool = False
    fallback_reason: str | None = None


class LeadEcho(BaseModel):
    """Contact fields echoed back so no-code tools can map everything from one step."""

    name: str
    email: str
    company: str | None = None
    source: str


class TriageResponse(TriageResult):
    lead: LeadEcho
    meta: TriageMeta


# JSON schema sent to Claude as the structured output format. Kept by hand
# (not generated) so it only uses keywords structured outputs supports; range
# and length limits are enforced afterwards by LLMTriage.
LLM_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "lead_score": {"type": "integer", "description": "0 to 100"},
        "score_reasons": {"type": "array", "items": {"type": "string"}, "description": "2 to 5 short reasons"},
        "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
        "budget_signal": {"type": "string", "enum": ["none", "mentioned", "explicit"]},
        "summary": {"type": "string", "description": "One sentence"},
        "company_guess": {"type": ["string", "null"]},
        "suggested_reply": {"type": "string"},
    },
    "required": [
        "category",
        "lead_score",
        "score_reasons",
        "urgency",
        "budget_signal",
        "summary",
        "company_guess",
        "suggested_reply",
    ],
    "additionalProperties": False,
}
