"""Orchestrates one triage: mock or live, then validation, routing and metering."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from .agent import AgentError, TriageAgent
from .config import Settings
from .guard import detect_injection
from .pricing import estimate_cost
from .rules_engine import rules_triage
from .schemas import Enrichment, LeadIn, LLMTriage, TriageMeta, TriageResponse, Usage
from .scoring import ScoringRules
from .tools import ToolBox, enrich_email_domain

log = logging.getLogger("triage")

INJECTION_REASON = "Contains instructions aimed at the AI"


def lead_id_for(lead: LeadIn) -> str:
    """Stable id from normalised email + message, shared with the Node worker's idempotency key."""
    basis = f"{lead.email.strip().lower()}\n{' '.join(lead.message.split()).lower()}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def build_client(settings: Settings) -> Any:
    import anthropic

    # The SDK retries 429/5xx/connection errors itself; keep it short so a
    # slow API degrades to the rules engine instead of hanging the webhook.
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=2, timeout=45.0)


class TriageService:
    def __init__(self, settings: Settings, rules: ScoringRules, client: Any | None = None):
        self.settings = settings
        self.rules = rules
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = build_client(self.settings)
        return self._client

    def _finalise(
        self,
        lead: LeadIn,
        triage: LLMTriage,
        enrichment: dict[str, Any],
        meta: TriageMeta,
    ) -> TriageResponse:
        # Facts about the email come from code, not from the model.
        facts = enrich_email_domain(lead.email, self.rules)
        company_guess = (
            triage.company_guess or lead.company or facts["company_guess"] or enrichment.get("company_guess")
        )
        reasons = list(triage.score_reasons)
        if meta.injection_detected and INJECTION_REASON not in reasons:
            reasons.append(INJECTION_REASON)
        routing = self.rules.route(triage.category, triage.lead_score, meta.injection_detected)
        return TriageResponse(
            category=triage.category,
            lead_score=triage.lead_score,
            score_reasons=reasons[:6],
            urgency=triage.urgency,
            budget_signal=triage.budget_signal,
            summary=triage.summary,
            enrichment=Enrichment(email_type=facts["email_type"], domain=facts["domain"], company_guess=company_guess),
            suggested_reply=triage.suggested_reply,
            routing=routing,
            meta=meta,
        )

    def triage(self, lead: LeadIn) -> TriageResponse:
        started = time.perf_counter()
        lead_id = lead_id_for(lead)
        injection = bool(detect_injection(f"{lead.name}\n{lead.company or ''}\n{lead.message}"))

        def meta(**kwargs: Any) -> TriageMeta:
            return TriageMeta(
                lead_id=lead_id,
                latency_ms=int((time.perf_counter() - started) * 1000),
                injection_detected=injection,
                **kwargs,
            )

        if self.settings.mock_mode:
            triage, enrichment = rules_triage(lead, self.rules)
            return self._finalise(lead, triage, enrichment, meta(mode="mock"))

        agent = TriageAgent(
            client=self.client,
            model=self.settings.anthropic_model,
            toolbox=ToolBox(self.rules, self.settings.enable_homepage_fetch, self.settings.homepage_fetch_timeout),
            effort=self.settings.effort,
            max_steps=self.settings.max_agent_steps,
            server_side_fallback=self.settings.server_side_fallback,
        )
        model = self.settings.anthropic_model
        try:
            outcome = agent.run(lead.model_dump())
        except AgentError as exc:
            log.warning("llm_fallback", extra={"lead_id": lead_id, "reason": str(exc)})
            triage, enrichment = rules_triage(lead, self.rules)
            return self._finalise(
                lead,
                triage,
                enrichment,
                meta(
                    mode="fallback",
                    model=model,
                    llm_calls=exc.llm_calls,
                    tool_calls=exc.tool_calls,
                    usage=exc.usage,
                    cost_usd=estimate_cost(model, exc.usage),
                    fallback_reason=str(exc)[:300],
                ),
            )
        except Exception as exc:  # API down, auth error, network: degrade, never drop the lead
            log.warning("llm_unavailable", extra={"lead_id": lead_id, "reason": type(exc).__name__})
            triage, enrichment = rules_triage(lead, self.rules)
            return self._finalise(
                lead,
                triage,
                enrichment,
                meta(mode="fallback", model=model, usage=Usage(), fallback_reason=f"{type(exc).__name__}: {exc}"[:300]),
            )

        return self._finalise(
            lead,
            outcome.triage,
            outcome.enrichment or {},
            meta(
                mode="live",
                model=model,
                llm_calls=outcome.llm_calls,
                tool_calls=outcome.tool_calls,
                usage=outcome.usage,
                cost_usd=estimate_cost(model, outcome.usage),
            ),
        )
