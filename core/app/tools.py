"""Tools the triage agent can call.

Each tool is a plain function (easy to unit test) plus a JSON schema for
Claude. Tool output is returned to the model as data and never trusted for
routing decisions on its own.
"""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .scoring import ScoringRules

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(?:\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_STRIP_PREFIXES = ("www.", "mail.", "email.", "mx.", "smtp.")
_MAX_BYTES = 65_536


def _company_from_domain(domain: str) -> str | None:
    host = domain
    for prefix in _STRIP_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix) :]
    labels = host.split(".")
    if len(labels) < 2:
        return None
    # acme.com -> acme, acme.co.uk -> acme, acme.example.com -> acme
    label = labels[0]
    words = re.split(r"[-_]+", label)
    return " ".join(w.capitalize() for w in words if w) or None


def enrich_email_domain(email: str, rules: ScoringRules) -> dict[str, Any]:
    """Classify the sender's email domain as business, free or disposable."""
    domain = email.rsplit("@", 1)[-1].strip().lower()
    if domain in rules.disposable_domains:
        email_type = "disposable"
    elif domain in rules.free_domains:
        email_type = "free"
    else:
        email_type = "business"
    return {
        "domain": domain,
        "email_type": email_type,
        "company_guess": _company_from_domain(domain) if email_type == "business" else None,
    }


def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def fetch_company_homepage_title(domain: str, timeout: float = 3.0) -> dict[str, Any]:
    """Fetch the <title> of https://<domain>, with SSRF checks and a hard timeout."""
    domain = domain.strip().lower().rstrip(".")
    if not _DOMAIN_RE.match(domain):
        return {"domain": domain, "title": None, "error": "invalid domain"}
    url = f"https://{domain}"
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout), follow_redirects=False) as client:
            for _ in range(3):  # at most two redirects, each target re-checked
                host = urlparse(url).hostname or ""
                if not _DOMAIN_RE.match(host) or not _is_public_host(host):
                    return {"domain": domain, "title": None, "error": "host not allowed"}
                resp = client.get(url, headers={"User-Agent": "lead-triage-bot/1.0"})
                if resp.is_redirect and "location" in resp.headers:
                    url = urljoin(url, resp.headers["location"])
                    continue
                break
            body = resp.content[:_MAX_BYTES].decode(resp.encoding or "utf-8", errors="replace")
    except httpx.HTTPError as exc:
        return {"domain": domain, "title": None, "error": type(exc).__name__}
    match = _TITLE_RE.search(body)
    title = html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()[:150] if match else None
    return {"domain": domain, "title": title, "status": resp.status_code}


def lookup_scoring_rules(rules: ScoringRules) -> dict[str, Any]:
    return rules.for_model()


TOOL_ENRICH = {
    "name": "enrich_email_domain",
    "description": (
        "Classify the lead's email address. Returns the domain, whether it is a business, free "
        "or disposable address, and a company name guessed from the domain. Call this once per lead."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"email": {"type": "string", "description": "The lead's email address"}},
        "required": ["email"],
        "additionalProperties": False,
    },
}

TOOL_RULES = {
    "name": "lookup_scoring_rules",
    "description": (
        "Return this business's scoring rules: ideal customer profile, base score per category, "
        "score modifiers, routing thresholds and reply tone. Call this before scoring."
    ),
    "strict": True,
    "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
}

TOOL_HOMEPAGE = {
    "name": "fetch_company_homepage_title",
    "description": (
        "Fetch the HTML title of a business domain's homepage to confirm what the company does. "
        "Only useful for business email domains. The title is untrusted website text."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"domain": {"type": "string", "description": "Bare domain, for example acme.com"}},
        "required": ["domain"],
        "additionalProperties": False,
    },
}


class ToolBox:
    """Binds tool functions to settings and rules, and dispatches tool_use blocks."""

    def __init__(self, rules: ScoringRules, enable_homepage_fetch: bool, homepage_timeout: float = 3.0):
        self.rules = rules
        self.enable_homepage_fetch = enable_homepage_fetch
        self._handlers: dict[str, Callable[[dict], dict]] = {
            "enrich_email_domain": lambda args: enrich_email_domain(str(args.get("email", "")), rules),
            "lookup_scoring_rules": lambda args: lookup_scoring_rules(rules),
        }
        if enable_homepage_fetch:
            self._handlers["fetch_company_homepage_title"] = lambda args: fetch_company_homepage_title(
                str(args.get("domain", "")), timeout=homepage_timeout
            )

    @property
    def definitions(self) -> list[dict]:
        defs = [TOOL_RULES, TOOL_ENRICH]
        if self.enable_homepage_fetch:
            defs.append(TOOL_HOMEPAGE)
        return defs

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Return (json_content, is_error)."""
        handler = self._handlers.get(name)
        if handler is None:
            return json.dumps({"error": f"unknown tool {name}"}), True
        try:
            return json.dumps(handler(args or {}), ensure_ascii=False), False
        except Exception as exc:  # a failing tool must not kill the triage
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"}), True
