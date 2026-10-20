from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

CORE = Path(__file__).resolve().parents[1]
ROOT = CORE.parent
sys.path.insert(0, str(CORE))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.scoring import load_rules  # noqa: E402

API_KEY = "test-key-123"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        anthropic_api_key=None,
        anthropic_model="claude-sonnet-5-5",
        mock_mode=True,
        api_keys=[API_KEY],
        rate_limit_per_minute=100,
        cors_origins=["http://localhost:8080"],
    )


@pytest.fixture
def live_settings(settings: Settings) -> Settings:
    return replace(settings, anthropic_api_key="sk-test", mock_mode=False)


@pytest.fixture
def rules(settings: Settings):
    return load_rules(settings.scoring_rules_path)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture
def headers() -> dict:
    return {"X-API-Key": API_KEY}


@pytest.fixture(scope="session")
def sample_leads() -> list[dict]:
    return json.loads((ROOT / "data" / "sample_leads.json").read_text())


def lead_payload(lead: dict) -> dict:
    return {k: lead[k] for k in ("name", "email", "company", "message", "source")}


# ---- Fake Anthropic SDK -------------------------------------------------


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_use(name: str, args: dict, id_: str) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=args)


def response(content: list, stop_reason: str, input_tokens: int = 1000, output_tokens: int = 200) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


class FakeAnthropic:
    """Replays scripted responses and records every request."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("FakeAnthropic ran out of scripted responses")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def tool_round(email: str) -> SimpleNamespace:
    return response(
        [
            tool_use("lookup_scoring_rules", {}, "tu_1"),
            tool_use("enrich_email_domain", {"email": email}, "tu_2"),
        ],
        "tool_use",
    )


def final_json(**overrides) -> SimpleNamespace:
    body = {
        "category": "sales_inquiry",
        "lead_score": 88,
        "score_reasons": ["Explicit budget", "Business email", "Two week timeline"],
        "urgency": "high",
        "budget_signal": "explicit",
        "summary": "Freight company wants AI lead qualification with a $15k budget.",
        "company_guess": "Brightpath Logistics",
        "suggested_reply": "Hi Dana, thanks for reaching out. Could we book a call this week?",
        "confidence": 0.9,
    }
    body.update(overrides)
    return response([text_block(json.dumps(body))], "end_turn", input_tokens=2500, output_tokens=350)
