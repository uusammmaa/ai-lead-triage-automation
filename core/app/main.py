"""FastAPI entrypoint: POST /triage and GET /health."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import Settings, get_settings
from .logging_setup import configure_logging
from .schemas import LeadIn, TriageResponse
from .scoring import load_rules
from .security import RateLimiter, rate_limit
from .triage import TriageService

log = logging.getLogger("api")


def create_app(settings: Settings | None = None, client: Any | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    rules = load_rules(settings.scoring_rules_path)

    app = FastAPI(
        title="AI Lead Triage",
        version=__version__,
        description="Classify, score, enrich and route inbound leads with a Claude agent.",
    )
    app.state.settings = settings
    app.state.rules = rules
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.service = TriageService(settings, rules, client=client)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        remaining = getattr(request.state, "rate_remaining", None)
        if remaining is not None:
            response.headers["X-RateLimit-Remaining"] = str(remaining)
        log.info(
            "http_request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            },
        )
        return response

    if not settings.auth_enabled:
        log.warning("auth_disabled", extra={"hint": "set API_KEYS to require X-API-Key"})
    log.info(
        "startup",
        extra={
            "mode": "mock" if settings.mock_mode else "live",
            "model": settings.anthropic_model,
            "version": __version__,
        },
    )

    @app.get("/health", tags=["ops"])
    def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "mode": "mock" if settings.mock_mode else "live",
            "model": None if settings.mock_mode else settings.anthropic_model,
            "auth": "api_key" if settings.auth_enabled else "disabled",
            "homepage_fetch": settings.enable_homepage_fetch,
        }

    @app.post("/triage", response_model=TriageResponse, tags=["triage"])
    def triage(lead: LeadIn, request: Request, key_id: str = Depends(rate_limit)) -> TriageResponse:
        result = request.app.state.service.triage(lead)
        log.info(
            "lead_triaged",
            extra={
                "request_id": request.state.request_id,
                "api_key": key_id,
                "lead_id": result.meta.lead_id,
                "source": lead.source,
                "email_domain": result.enrichment.domain,  # never log the message body
                "category": result.category,
                "lead_score": result.lead_score,
                "routing": result.routing,
                "mode": result.meta.mode,
                "latency_ms": result.meta.latency_ms,
                "input_tokens": result.meta.usage.input_tokens,
                "output_tokens": result.meta.usage.output_tokens,
                "cost_usd": result.meta.cost_usd,
                "injection_detected": result.meta.injection_detected,
                "fallback_reason": result.meta.fallback_reason,
            },
        )
        return result

    return app


app = create_app()
