import httpx
import pytest

from app import tools
from app.tools import ToolBox, enrich_email_domain, fetch_company_homepage_title


@pytest.mark.parametrize(
    "email,email_type,company",
    [
        ("dana@brightpath-logistics.example.com", "business", "Brightpath Logistics"),
        ("ceo@mail.acme.co.uk", "business", "Acme"),
        ("someone@gmail.com", "free", None),
        ("grace@freemail.example.com", "free", None),
        ("x@mailinator.com", "disposable", None),
        ("x@tempinbox.example.com", "disposable", None),
    ],
)
def test_enrich_email_domain(rules, email, email_type, company):
    result = enrich_email_domain(email, rules)
    assert result["email_type"] == email_type
    assert result["domain"] == email.split("@")[1]
    assert result["company_guess"] == company


def _patch_http(monkeypatch, handler):
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(tools.httpx, "Client", factory)
    monkeypatch.setattr(tools, "_is_public_host", lambda host: True)


def test_homepage_title_is_extracted(monkeypatch):
    _patch_http(
        monkeypatch, lambda req: httpx.Response(200, html="<html><title> Acme &amp; Co | Freight </title></html>")
    )
    result = fetch_company_homepage_title("acme.example.com")
    assert result["title"] == "Acme & Co | Freight"


def test_homepage_redirect_is_followed(monkeypatch):
    def handler(req):
        if req.url.host == "acme.example.com":
            return httpx.Response(301, headers={"location": "https://www.acme.example.com/"})
        return httpx.Response(200, html="<title>Acme</title>")

    _patch_http(monkeypatch, handler)
    assert fetch_company_homepage_title("acme.example.com")["title"] == "Acme"


def test_homepage_timeout_returns_error_not_exception(monkeypatch):
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    _patch_http(monkeypatch, handler)
    result = fetch_company_homepage_title("slow.example.com", timeout=3.0)
    assert result["title"] is None and result["error"] == "ReadTimeout"


@pytest.mark.parametrize("domain", ["localhost", "127.0.0.1", "http://evil.example.com", "a b.com", "../etc"])
def test_homepage_rejects_unsafe_targets(domain):
    result = fetch_company_homepage_title(domain)
    assert result["title"] is None
    assert result["error"] in {"invalid domain", "host not allowed"}


def test_private_ip_hosts_are_blocked(monkeypatch):
    monkeypatch.setattr(tools.socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("10.0.0.5", 443))])
    assert fetch_company_homepage_title("intranet.example.com")["error"] == "host not allowed"


def test_homepage_tool_hidden_unless_flag_enabled(rules):
    assert "fetch_company_homepage_title" not in [t["name"] for t in ToolBox(rules, False).definitions]
    assert "fetch_company_homepage_title" in [t["name"] for t in ToolBox(rules, True).definitions]


def test_toolbox_reports_unknown_tool_as_error(rules):
    content, is_error = ToolBox(rules, False).run("delete_everything", {})
    assert is_error and "unknown tool" in content


def test_scoring_rules_tool_hides_keyword_lists(rules):
    content, is_error = ToolBox(rules, False).run("lookup_scoring_rules", {})
    assert not is_error
    assert "ideal_customer" in content and "keywords" not in content
