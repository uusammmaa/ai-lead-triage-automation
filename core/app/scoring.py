"""Loads the client-editable scoring rules and applies routing policy."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROUTING_ORDER = ["discard", "cold", "warm", "hot"]


@dataclass(frozen=True)
class ScoringRules:
    raw: dict[str, Any]

    @property
    def free_domains(self) -> set[str]:
        return {d.lower() for d in self.raw["email_domains"]["free"]}

    @property
    def disposable_domains(self) -> set[str]:
        return {d.lower() for d in self.raw["email_domains"]["disposable"]}

    @property
    def routing(self) -> dict[str, Any]:
        return self.raw["routing"]

    def for_model(self) -> dict[str, Any]:
        """The subset Claude sees through the lookup_scoring_rules tool.

        Keyword lists are left out on purpose: they exist for the offline
        engine, and showing them to the model nudges it towards keyword
        matching instead of reading the lead.
        """
        return {
            "business": self.raw["business"],
            "routing": self.raw["routing"],
            "scoring": self.raw["scoring"],
            "reply": self.raw["reply"],
            "notes": [
                "Start from category_base, then apply modifiers that clearly apply.",
                "Clamp the final score to 0..100.",
                "Routing is computed by the system from your score and category.",
            ],
        }

    def route(self, category: str, score: int, injection_detected: bool) -> str:
        overrides = self.routing.get("category_overrides", {}) or {}
        if category in overrides:
            routing = overrides[category]
        elif score >= int(self.routing["hot_min_score"]):
            routing = "hot"
        elif score >= int(self.routing["warm_min_score"]):
            routing = "warm"
        else:
            routing = "cold"
        if injection_detected:
            cap = self.routing.get("max_routing_when_injection_detected", "warm")
            if ROUTING_ORDER.index(routing) > ROUTING_ORDER.index(cap):
                routing = cap
        return routing


def load_rules(path: Path) -> ScoringRules:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    for key in ("routing", "scoring", "keywords", "email_domains", "reply", "business"):
        if key not in raw:
            raise ValueError(f"scoring rules file {path} is missing the '{key}' section")
    return ScoringRules(raw=raw)


@lru_cache(maxsize=4)
def get_rules(path: str) -> ScoringRules:
    return load_rules(Path(path))
