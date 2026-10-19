"""Runtime settings, read from environment variables.

A plain dataclass keeps the dependency list short; every value has a safe
local default so `uvicorn app.main:app` works with an empty environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_ESCALATION_MODEL = "claude-sonnet-5-5"
DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "config" / "scoring_rules.yaml"


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None
    anthropic_model: str
    mock_mode: bool
    api_keys: list[str] = field(default_factory=list)
    rate_limit_per_minute: int = 60
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    enable_homepage_fetch: bool = False
    homepage_fetch_timeout: float = 3.0
    scoring_rules_path: Path = DEFAULT_RULES_PATH
    server_side_fallback: bool = True
    effort: str = "low"
    max_agent_steps: int = 6
    log_level: str = "INFO"
    # Escalation: re-run a lead once on a stronger model when the cheap one is unsure or fails.
    escalation_model: str | None = DEFAULT_ESCALATION_MODEL
    escalation_threshold: float = 0.6
    # Cost and quality levers.
    prompt_caching: bool = True
    few_shot: bool = True
    prefilter: bool = True
    max_output_tokens: int = 1500
    temperature: float | None = None

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)


def _api_key() -> str | None:
    # LEAD_TRIAGE_API_KEY is a fallback for hosts that reserve or strip ANTHROPIC_API_KEY.
    for name in ("ANTHROPIC_API_KEY", "LEAD_TRIAGE_API_KEY"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def load_settings() -> Settings:
    api_key = _api_key()
    mock_raw = os.getenv("MOCK_MODE", "auto").strip().lower()
    if mock_raw in {"1", "true", "yes", "on"}:
        mock = True
    elif mock_raw in {"0", "false", "no", "off"}:
        mock = api_key is None  # cannot run live without a key
    else:
        mock = api_key is None
    return Settings(
        anthropic_api_key=api_key,
        anthropic_model=os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        mock_mode=mock,
        api_keys=_list("API_KEYS"),
        rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")),
        cors_origins=_list("CORS_ORIGINS", "*") or ["*"],
        enable_homepage_fetch=_bool("ENABLE_HOMEPAGE_FETCH", False),
        homepage_fetch_timeout=float(os.getenv("HOMEPAGE_FETCH_TIMEOUT", "3")),
        scoring_rules_path=Path(os.getenv("SCORING_RULES_PATH", str(DEFAULT_RULES_PATH))),
        server_side_fallback=_bool("ANTHROPIC_SERVER_SIDE_FALLBACK", True),
        effort=os.getenv("ANTHROPIC_EFFORT", "low").strip() or "low",
        max_agent_steps=int(os.getenv("MAX_AGENT_STEPS", "6")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        escalation_model=(os.getenv("ESCALATION_MODEL", DEFAULT_ESCALATION_MODEL).strip() or None),
        escalation_threshold=float(os.getenv("ESCALATION_CONFIDENCE_THRESHOLD", "0.6")),
        prompt_caching=_bool("PROMPT_CACHING", True),
        few_shot=_bool("FEW_SHOT_EXAMPLES", True),
        prefilter=_bool("RULES_PREFILTER", True),
        max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "1500")),
        temperature=float(os.environ["TEMPERATURE"]) if os.getenv("TEMPERATURE", "").strip() else None,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
