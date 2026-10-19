"""Evaluate the triage core against the labelled sample leads.

Usage:
    python evals/run_evals.py              # mock mode unless ANTHROPIC_API_KEY is set
    python evals/run_evals.py --mode mock  # force the offline rules engine
    python evals/run_evals.py --mode live  # real Claude calls (needs ANTHROPIC_API_KEY)

Writes evals/results.md (human readable) and evals/results.json (for CI).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from app.agent import SYSTEM_PROMPT  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.guard import wrap_lead  # noqa: E402
from app.pricing import estimate_cost  # noqa: E402
from app.schemas import LeadIn, Usage  # noqa: E402
from app.scoring import load_rules  # noqa: E402
from app.tools import ToolBox, enrich_email_domain  # noqa: E402
from app.triage import TriageService  # noqa: E402

FIELDS = ("name", "email", "company", "message", "source")
# Rough English token estimate. Good enough for a projection, labelled as such.
CHARS_PER_TOKEN = 4.0
EST_TOOL_CALL_OUTPUT_TOKENS = 120
EST_FINAL_OUTPUT_TOKENS = 450  # JSON answer plus low-effort thinking


def projected_usage(lead: LeadIn, toolbox: ToolBox) -> Usage:
    """Estimate tokens for the usual 2-call agent run (tools, then answer), no caching."""

    def tok(text: str) -> int:
        return int(len(text) / CHARS_PER_TOKEN)

    static = tok(SYSTEM_PROMPT) + tok(json.dumps(toolbox.definitions))
    lead_tokens = tok(wrap_lead(lead.model_dump()))
    tool_results = tok(json.dumps(toolbox.rules.for_model())) + tok(
        json.dumps(enrich_email_domain(lead.email, toolbox.rules))
    )
    call1_in = static + lead_tokens
    call2_in = call1_in + EST_TOOL_CALL_OUTPUT_TOKENS + tool_results
    return Usage(input_tokens=call1_in + call2_in, output_tokens=EST_TOOL_CALL_OUTPUT_TOKENS + EST_FINAL_OUTPUT_TOKENS)


def pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.1f}%" if d else "n/a"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["auto", "mock", "live"], default="auto")
    parser.add_argument("--data", default=str(ROOT / "data" / "sample_leads.json"))
    parser.add_argument("--out", default=str(ROOT / "evals" / "results.md"))
    parser.add_argument("--min-category-accuracy", type=float, default=0.0, help="exit 1 below this (0..1)")
    args = parser.parse_args()

    settings = load_settings()
    if args.mode == "mock":
        settings = replace(settings, mock_mode=True)
    elif args.mode == "live":
        if not settings.anthropic_api_key:
            print("--mode live needs ANTHROPIC_API_KEY", file=sys.stderr)
            return 2
        settings = replace(settings, mock_mode=False)
    rules = load_rules(settings.scoring_rules_path)
    service = TriageService(settings, rules)
    toolbox = ToolBox(rules, settings.enable_homepage_fetch)

    leads = json.loads(Path(args.data).read_text())
    rows = []
    for lead in leads:
        lead_in = LeadIn(**{k: lead.get(k) for k in FIELDS})
        result = service.triage(lead_in)
        rows.append(
            {
                "id": lead["id"],
                "tags": lead.get("tags", []),
                "expected_category": lead["expected_category"],
                "expected_routing": lead["expected_routing"],
                "category": result.category,
                "routing": result.routing,
                "lead_score": result.lead_score,
                "mode": result.meta.mode,
                "latency_ms": result.meta.latency_ms,
                "usage": result.meta.usage.model_dump(),
                "cost_usd": result.meta.cost_usd,
                "injection_detected": result.meta.injection_detected,
                "projected": projected_usage(lead_in, toolbox).model_dump(),
            }
        )
        print(f"{lead['id']}: {result.category:<14} {result.routing:<8} score={result.lead_score:<3} {result.meta.mode}")

    n = len(rows)
    cat_ok = sum(r["category"] == r["expected_category"] for r in rows)
    route_ok = sum(r["routing"] == r["expected_routing"] for r in rows)
    inj = [r for r in rows if "prompt_injection" in r["tags"]]
    inj_ok = sum(r["category"] == r["expected_category"] and r["routing"] == r["expected_routing"] for r in inj)
    latencies = [r["latency_ms"] for r in rows]
    modes = Counter(r["mode"] for r in rows)
    measured_cost = sum(r["cost_usd"] for r in rows)
    measured_per_1k = measured_cost / n * 1000 if n else 0.0
    model = settings.anthropic_model
    proj_usage = Usage(
        input_tokens=sum(r["projected"]["input_tokens"] for r in rows),
        output_tokens=sum(r["projected"]["output_tokens"] for r in rows),
    )
    projected_per_1k = estimate_cost(model, proj_usage) / n * 1000 if n else 0.0
    avg_in = proj_usage.input_tokens // n if n else 0
    avg_out = proj_usage.output_tokens // n if n else 0
    misses = [r for r in rows if r["category"] != r["expected_category"] or r["routing"] != r["expected_routing"]]
    run_mode = "mock" if settings.mock_mode else "live"

    summary = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": run_mode,
        "model": None if settings.mock_mode else model,
        "leads": n,
        "category_accuracy": cat_ok / n if n else 0,
        "routing_accuracy": route_ok / n if n else 0,
        "injection_resisted": f"{inj_ok}/{len(inj)}",
        "avg_latency_ms": statistics.mean(latencies) if latencies else 0,
        "p95_latency_ms": sorted(latencies)[int(0.95 * (n - 1))] if latencies else 0,
        "modes": dict(modes),
        "measured_cost_per_1000_usd": round(measured_per_1k, 4),
        "projected_live_cost_per_1000_usd": round(projected_per_1k, 2),
        "projected_tokens_per_lead": {"input": avg_in, "output": avg_out},
        "misses": [
            {k: r[k] for k in ("id", "expected_category", "category", "expected_routing", "routing")} for r in misses
        ],
    }

    lines = [
        "# Eval results",
        "",
        f"Run: {summary['run_at']} | mode: **{run_mode}**"
        + (f" | model: `{model}`" if run_mode == "live" else "")
        + f" | leads: {n} | modes seen: {dict(modes)}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Category accuracy | {pct(cat_ok, n)} ({cat_ok}/{n}) |",
        f"| Routing accuracy | {pct(route_ok, n)} ({route_ok}/{n}) |",
        f"| Prompt injection resisted | {inj_ok}/{len(inj)} |",
        f"| Avg latency | {summary['avg_latency_ms']:.1f} ms |",
        f"| p95 latency | {summary['p95_latency_ms']} ms |",
        f"| Measured cost per 1,000 leads | ${measured_per_1k:.2f} |",
        f"| Projected live cost per 1,000 leads (`{model}`) | ${projected_per_1k:.2f} |",
        "",
        "## Per category",
        "",
        "| Category | Leads | Correct |",
        "| --- | --- | --- |",
    ]
    for cat in sorted({r["expected_category"] for r in rows}):
        subset = [r for r in rows if r["expected_category"] == cat]
        ok = sum(r["category"] == cat for r in subset)
        lines.append(f"| {cat} | {len(subset)} | {ok} |")
    lines += ["", "## Misses", ""]
    if misses:
        lines += ["| Lead | Expected | Got |", "| --- | --- | --- |"]
        for r in misses:
            lines.append(
                f"| {r['id']} | {r['expected_category']} / {r['expected_routing']} | {r['category']} / {r['routing']} |"
            )
    else:
        lines.append("None.")
    lines += [
        "",
        "## How to read this",
        "",
        "- **Mock mode** runs the deterministic rules engine. Its keyword lists were written alongside this",
        "  dataset, so a high mock score proves the pipeline, schema and routing work end to end. It is not a",
        "  benchmark of the AI. Run `--mode live` with an API key for the model's real numbers.",
        "- **Measured cost** comes from real token usage reported by the API. It is $0 in mock mode.",
        f"- **Projected live cost** estimates a typical 2-call agent run per lead (about {avg_in:,} input and",
        f"  {avg_out:,} output tokens, {CHARS_PER_TOKEN:.0f} characters per token, no prompt caching) at list",
        "  prices. Prompt caching of the system prompt and tools lowers the real figure.",
        "- Latency in mock mode is local CPU time. Live latency is dominated by the model call.",
        "",
    ]
    Path(args.out).write_text("\n".join(lines))
    Path(args.out).with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n")
    print("\n".join(lines[4:13]))

    if summary["category_accuracy"] < args.min_category_accuracy:
        print(f"category accuracy below threshold {args.min_category_accuracy}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    sys.exit(main())
