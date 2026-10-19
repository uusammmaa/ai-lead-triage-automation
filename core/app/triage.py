"""Orchestrates one triage: mock or live, then validation, routing and metering."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any

from .agent import AgentError, AgentOutcome, TriageAgent
from .config import Settings
from .guard import detect_injection
from .pricing import estimate_cost
from .rules_engine import prefilter_reason, rules_triage
from .schemas import Enrichment, LeadEcho, LeadIn, LLMTriage, TriageMeta, TriageResponse, Usage
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
        self.stats = TriageStats()

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
            confidence=triage.confidence,
            lead=LeadEcho(name=lead.name, email=lead.email, company=lead.company, source=lead.source),
            meta=meta,
        )

    def _agent(self, model: str) -> TriageAgent:
        st = self.settings
        return TriageAgent(
            client=self.client,
            model=model,
            toolbox=ToolBox(self.rules, st.enable_homepage_fetch, st.homepage_fetch_timeout),
            effort=st.effort,
            max_steps=st.max_agent_steps,
            server_side_fallback=st.server_side_fallback,
            max_tokens=st.max_output_tokens,
            prompt_caching=st.prompt_caching,
            few_shot=st.few_shot,
            temperature=st.temperature,
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

        if self.settings.prefilter:
            reason = prefilter_reason(lead, self.rules)
            if reason:
                triage, enrichment = rules_triage(lead, self.rules)
                self.stats.record_prefilter()
                log.info("prefilter_skip", extra={"lead_id": lead_id, "reason": reason, **self.stats.snapshot()})
                return self._finalise(lead, triage, enrichment, meta(mode="prefilter", prefilter_reason=reason))

        if self.settings.mock_mode:
            triage, enrichment = rules_triage(lead, self.rules)
            return self._finalise(lead, triage, enrichment, meta(mode="mock"))

        primary = self.settings.anthropic_model
        escalation = self.settings.escalation_model
        if escalation == primary:
            escalation = None
        run = _RunTotals()
        outcome: AgentOutcome | None = None
        final_model = primary
        escalate_reason: str | None = None
        failure: str | None = None

        try:
            first = self._agent(primary).run(lead.model_dump())
            run.add(primary, first.usage, first.llm_calls, first.tool_calls)
            confidence = first.triage.confidence
            outcome = first
            if escalation and confidence is not None and confidence < self.settings.escalation_threshold:
                escalate_reason = f"low confidence {confidence:.2f}"
        except AgentError as exc:
            run.add(primary, exc.usage, exc.llm_calls, exc.tool_calls)
            failure = str(exc)
            if escalation:
                escalate_reason = f"{primary} failed: {exc}"[:200]
        except Exception as exc:  # API down, auth error, network: degrade, never drop the lead
            log.warning("llm_unavailable", extra={"lead_id": lead_id, "reason": type(exc).__name__})
            failure = f"{type(exc).__name__}: {exc}"

        if escalate_reason and escalation:
            self.stats.record_escalation()
            try:
                second = self._agent(escalation).run(lead.model_dump())
                run.add(escalation, second.usage, second.llm_calls, second.tool_calls)
                outcome, failure, final_model = second, None, escalation
            except AgentError as exc:
                run.add(escalation, exc.usage, exc.llm_calls, exc.tool_calls)
                failure = failure or str(exc)
            except Exception as exc:
                failure = failure or f"{type(exc).__name__}: {exc}"
            log.info(
                "escalated",
                extra={
                    "lead_id": lead_id,
                    "reason": escalate_reason,
                    "ok": outcome is not None,
                    **self.stats.snapshot(),
                },
            )

        common = {
            "llm_calls": run.llm_calls,
            "tool_calls": run.tool_calls,
            "usage": run.usage,
            "cost_usd": round(run.cost, 6),
            "models_used": run.models,
            "escalated": bool(escalate_reason and escalation),
            "escalation_reason": escalate_reason if escalation else None,
        }
        if outcome is None:
            self.stats.record_llm(fallback=True)
            log.warning("llm_fallback", extra={"lead_id": lead_id, "reason": (failure or "")[:300]})
            triage, enrichment = rules_triage(lead, self.rules)
            return self._finalise(
                lead,
                triage,
                enrichment,
                meta(mode="fallback", model=primary, fallback_reason=(failure or "unknown")[:300], **common),
            )

        self.stats.record_llm(fallback=False)
        # If escalation failed after a valid low-confidence answer, that answer is kept (final_model = primary).
        return self._finalise(
            lead, outcome.triage, outcome.enrichment or {}, meta(mode="live", model=final_model, **common)
        )


class _RunTotals:
    """Token, call and cost totals across the primary and escalation models."""

    def __init__(self) -> None:
        self.usage = Usage()
        self.cost = 0.0
        self.llm_calls = 0
        self.tool_calls: list[str] = []
        self.models: list[str] = []

    def add(self, model: str, usage: Usage, llm_calls: int, tool_calls: list[str]) -> None:
        for field in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            setattr(self.usage, field, getattr(self.usage, field) + getattr(usage, field))
        self.cost += estimate_cost(model, usage)
        self.llm_calls += llm_calls
        self.tool_calls += tool_calls
        if llm_calls:
            self.models.append(model)


class TriageStats:
    """Process-wide counters: how many model calls the pre-filter saved, how often we escalate."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.leads = 0
        self.prefiltered = 0
        self.llm_leads = 0
        self.escalated = 0
        self.fallbacks = 0

    def record_prefilter(self) -> None:
        with self._lock:
            self.leads += 1
            self.prefiltered += 1

    def record_escalation(self) -> None:
        with self._lock:
            self.escalated += 1

    def record_llm(self, fallback: bool) -> None:
        with self._lock:
            self.leads += 1
            self.llm_leads += 1
            self.fallbacks += int(fallback)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "leads_total": self.leads,
                "prefiltered_total": self.prefiltered,
                "model_runs_saved_by_prefilter": self.prefiltered,
                "escalated_total": self.escalated,
                "escalation_rate": round(self.escalated / self.llm_leads, 4) if self.llm_leads else 0.0,
                "fallback_total": self.fallbacks,
            }
