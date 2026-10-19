"""Evaluate the triage core on labelled leads, per model configuration, with a hard spend cap.

Examples:
    python evals/run_evals.py --config mock --data sample holdout      # offline, $0 (CI)
    python evals/run_evals.py --config haiku --data holdout            # live, needs ANTHROPIC_API_KEY
    python evals/run_evals.py --matrix                                 # the 3 live configs, then the report
    python evals/run_evals.py --report                                 # rebuild results.md + README table

Configs:
    mock              rules engine only (no API calls)
    haiku             claude-haiku-5-5, no escalation
    haiku_escalation  claude-haiku-5-5, escalates to claude-sonnet-5-5 when unsure or invalid (default)
    sonnet            claude-sonnet-5-5 only

Every live call's measured cost is appended to evals/spend_ledger.json. A run
stops before a lead whose worst-case cost would push the ledger past --stop-at.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("LOG_LEVEL", "WARNING")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from app.config import DEFAULT_ESCALATION_MODEL, DEFAULT_MODEL, load_settings  # noqa: E402
from app.schemas import CATEGORIES, LeadIn  # noqa: E402
from app.scoring import load_rules  # noqa: E402
from app.triage import TriageService  # noqa: E402

EVALS = ROOT / "evals"
RUNS = EVALS / "runs"
LEDGER = EVALS / "spend_ledger.json"
RESULTS = EVALS / "results.md"
README = ROOT / "README.md"
DATASETS = {"sample": ROOT / "data" / "sample_leads.json", "holdout": ROOT / "data" / "holdout_leads.json"}
FIELDS = ("name", "email", "company", "message", "source")
DEFAULT_CONFIG = "haiku_escalation"
CONFIGS = {
    "mock": {"mock": True, "model": None, "escalation": None, "label": "Mock (rules engine)"},
    "haiku": {"mock": False, "model": DEFAULT_MODEL, "escalation": None, "label": "Haiku only"},
    "haiku_escalation": {
        "mock": False,
        "model": DEFAULT_MODEL,
        "escalation": DEFAULT_ESCALATION_MODEL,
        "label": "Haiku + Sonnet escalation",
    },
    "sonnet": {"mock": False, "model": DEFAULT_ESCALATION_MODEL, "escalation": None, "label": "Sonnet only"},
}
# Worst-case cost of one lead, used only to stop before the budget is crossed.
RESERVE_PER_LEAD = {"mock": 0.0, "haiku": 0.004, "haiku_escalation": 0.05, "sonnet": 0.05}
MATRIX = [("haiku", ["sample", "holdout"]), ("haiku_escalation", ["sample", "holdout"]), ("sonnet", ["holdout"])]


# ---- spend ledger --------------------------------------------------------------


def load_ledger(budget: float) -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"budget_usd": budget, "total_usd": 0.0, "runs": []}


def save_ledger(ledger: dict) -> None:
    ledger["total_usd"] = round(sum(r["cost_usd"] for r in ledger["runs"]), 6)
    LEDGER.write_text(json.dumps(ledger, indent=2) + "\n")


# ---- running ---------------------------------------------------------------------


def run_config(config: str, datasets: list[str], tag: str, stop_at: float, budget: float) -> dict:
    spec = CONFIGS[config]
    settings = load_settings()
    if spec["mock"]:
        settings = replace(settings, mock_mode=True)
    else:
        if not settings.anthropic_api_key:
            raise SystemExit("Live configs need ANTHROPIC_API_KEY. Mock runs work without it: --config mock")
        settings = replace(
            settings, mock_mode=False, anthropic_model=spec["model"], escalation_model=spec["escalation"]
        )
    rules = load_rules(settings.scoring_rules_path)
    service = TriageService(settings, rules)
    ledger = load_ledger(budget)
    run_id = f"{config}@{tag}"
    out = {
        "run_id": run_id,
        "config": config,
        "label": spec["label"],
        "tag": tag,
        "model": spec["model"],
        "escalation_model": spec["escalation"],
        "levers": {
            "prompt_caching": settings.prompt_caching,
            "few_shot": settings.few_shot,
            "prefilter": settings.prefilter,
            "effort": settings.effort,
            "max_output_tokens": settings.max_output_tokens,
            "escalation_threshold": settings.escalation_threshold,
        },
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "datasets": {},
        "stopped_for_budget": False,
    }
    for dataset in datasets:
        leads = json.loads(DATASETS[dataset].read_text())
        rows, spent = [], 0.0
        for lead in leads:
            if ledger["total_usd"] + spent + RESERVE_PER_LEAD[config] > stop_at:
                out["stopped_for_budget"] = True
                print(
                    f"STOP: ledger ${ledger['total_usd'] + spent:.4f} is near the ${stop_at:.2f} cap", file=sys.stderr
                )
                break
            started = time.perf_counter()
            result = service.triage(LeadIn(**{k: lead.get(k) for k in FIELDS}))
            wall_ms = int((time.perf_counter() - started) * 1000)
            reason = result.meta.fallback_reason or ""
            if any(e in reason for e in ("AuthenticationError", "PermissionDeniedError", "NotFoundError")):
                raise SystemExit(f"API rejected the request, aborting run: {reason}")
            spent += result.meta.cost_usd
            rows.append(
                {
                    "id": lead["id"],
                    "tags": lead.get("tags", []),
                    "expected_category": lead["expected_category"],
                    "expected_routing": lead["expected_routing"],
                    "category": result.category,
                    "routing": result.routing,
                    "lead_score": result.lead_score,
                    "confidence": result.confidence,
                    "mode": result.meta.mode,
                    "model": result.meta.model,
                    "models_used": result.meta.models_used,
                    "escalated": result.meta.escalated,
                    "escalation_reason": result.meta.escalation_reason,
                    "prefilter_reason": result.meta.prefilter_reason,
                    "fallback_reason": result.meta.fallback_reason,
                    "llm_calls": result.meta.llm_calls,
                    "latency_ms": wall_ms,
                    "cost_usd": result.meta.cost_usd,
                    "usage": result.meta.usage.model_dump(),
                    "summary": result.summary,
                    "score_reasons": result.score_reasons,
                }
            )
            ok = "ok " if result.category == lead["expected_category"] else "MISS"
            print(
                f"[{run_id}:{dataset}] {lead['id']} {ok} {result.category:<13} {result.routing:<7} "
                f"conf={result.confidence} {result.meta.mode:<9} ${result.meta.cost_usd:.5f}"
            )
        out["datasets"][dataset] = {"rows": rows, "summary": summarise(rows, len(leads))}
        if not spec["mock"]:
            ledger["runs"].append(
                {
                    "run_id": run_id,
                    "dataset": dataset,
                    "leads": len(rows),
                    "cost_usd": round(spent, 6),
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
            save_ledger(ledger)
            print(f"[{run_id}:{dataset}] spent ${spent:.4f}, ledger total ${ledger['total_usd']:.4f}")
        if out["stopped_for_budget"]:
            break
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{run_id}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    return out


def pct_value(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def summarise(rows: list[dict], dataset_size: int) -> dict:
    n = len(rows)
    model_rows = [r for r in rows if r["mode"] in ("live", "fallback")]
    injections = [r for r in rows if "prompt_injection" in r["tags"]]
    cost = sum(r["cost_usd"] for r in rows)
    usage = Counter()
    for r in rows:
        usage.update(r["usage"])
    latencies = [r["latency_ms"] for r in rows]
    model_latencies = [r["latency_ms"] for r in model_rows]
    return {
        "leads": n,
        "complete": n == dataset_size,
        "category_correct": sum(r["category"] == r["expected_category"] for r in rows),
        "routing_correct": sum(r["routing"] == r["expected_routing"] for r in rows),
        "injection_resisted": sum(
            r["category"] == r["expected_category"] and r["routing"] == r["expected_routing"] for r in injections
        ),
        "injection_total": len(injections),
        "prefiltered": sum(r["mode"] == "prefilter" for r in rows),
        "model_leads": len(model_rows),
        "escalated": sum(bool(r["escalated"]) for r in rows),
        "fallbacks": sum(r["mode"] == "fallback" for r in rows),
        "p50_ms": pct_value(latencies, 0.5),
        "p95_ms": pct_value(latencies, 0.95),
        "p50_model_ms": pct_value(model_latencies, 0.5),
        "cost_usd": round(cost, 6),
        "cost_per_1000_usd": round(cost / n * 1000, 4) if n else 0.0,
        "usage": dict(usage),
    }


# ---- reporting -----------------------------------------------------------------------


def load_runs() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(RUNS.glob("*.json"))} if RUNS.exists() else {}


def fmt_pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}% ({a}/{b})" if b else "n/a"


def merged(run: dict) -> tuple[list[dict], dict]:
    rows = [r for d in run["datasets"].values() for r in d["rows"]]
    size = sum(d["summary"]["leads"] for d in run["datasets"].values())
    return rows, summarise(rows, size)


def summary_row(label: str, dataset: str, s: dict) -> str:
    esc = fmt_pct(s["escalated"], s["model_leads"]) if s["model_leads"] else "n/a"
    partial = "" if s["complete"] else " (partial)"
    return (
        f"| {label} | {dataset}{partial} | {fmt_pct(s['category_correct'], s['leads'])} | "
        f"{fmt_pct(s['routing_correct'], s['leads'])} | {s['injection_resisted']}/{s['injection_total']} | {esc} | "
        f"{s['prefiltered']} of {s['leads']} | {s['p50_ms']} / {s['p95_ms']} ms | ${s['cost_per_1000_usd']:.2f} |"
    )


TABLE_HEAD = [
    "| Config | Dataset | Category acc. | Routing acc. | Injection resisted | Escalation rate | "
    "Skipped by pre-filter | p50 / p95 latency | Cost per 1,000 leads |",
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
]


def results_table(runs: dict[str, dict], tag: str) -> list[str]:
    lines = list(TABLE_HEAD)
    for config in ("haiku", "haiku_escalation", "sonnet", "mock"):
        run = runs.get(f"{config}@{tag}")
        if not run:
            continue
        for dataset, d in run["datasets"].items():
            lines.append(summary_row(run["label"], dataset, d["summary"]))
    return lines


def confusion(rows: list[dict]) -> list[str]:
    cats = list(CATEGORIES)
    counts = Counter((r["expected_category"], r["category"]) for r in rows)
    lines = ["| expected \\ predicted | " + " | ".join(cats) + " |", "| --- |" + " --- |" * len(cats)]
    for exp in cats:
        cells = [
            f"**{counts[(exp, p)]}**" if exp == p and counts[(exp, p)] else str(counts[(exp, p)] or ".") for p in cats
        ]
        lines.append(f"| {exp} | " + " | ".join(cells) + " |")
    return lines


def build_report(tag: str, compare: str | None) -> str:
    runs = load_runs()
    ledger = load_ledger(2.0)
    live = [r for r in runs.values() if r["config"] != "mock"]
    lines = ["# Eval results", ""]
    lines.append(
        "Datasets: `data/sample_leads.json` (30 leads, written with the rules) and `data/holdout_leads.json` "
        "(40 hard leads written later: German, Urdu, Arabic, one-liners, long rambling messages, recruiters, "
        "partnerships disguised as sales, 3 new injection styles)."
    )
    lines.append("")
    if not live:
        lines += [
            "> **Live runs have not been executed yet.** Only mock mode (the offline rules engine) is shown. "
            "Run `python evals/run_evals.py --matrix` with `ANTHROPIC_API_KEY` set to fill in the model rows.",
            "",
        ]
    lines += [f"## Results (prompt `{tag}`)", ""] + results_table(runs, tag) + [""]
    lines += [
        "Cost per 1,000 leads is measured from API-reported token usage (cache reads and writes priced separately) "
        "and includes leads the pre-filter skipped at $0. Latency is wall-clock per lead, sequential.",
        "",
    ]
    if compare:
        lines += [f"## Before and after the prompt change (`{compare}` to `{tag}`)", ""] + list(TABLE_HEAD)
        for config in ("haiku", "haiku_escalation"):
            for t in (compare, tag):
                run = runs.get(f"{config}@{t}")
                if run:
                    for dataset, d in run["datasets"].items():
                        lines.append(summary_row(f"{run['label']} `{t}`", dataset, d["summary"]))
        lines.append("")
    default = runs.get(f"{DEFAULT_CONFIG}@{tag}") or runs.get(f"mock@{tag}")
    if default:
        rows, _ = merged(default)
        lines += [f"## Confusion matrix: {default['label']} (sample + holdout, {len(rows)} leads)", ""]
        lines += confusion(rows) + [""]
        misses = [r for r in rows if r["category"] != r["expected_category"] or r["routing"] != r["expected_routing"]]
        lines += [f"## What {default['label']} gets wrong ({len(misses)} of {len(rows)})", ""]
        notes = EVALS / f"analysis_{tag}.md"
        if notes.exists():
            lines += [notes.read_text().strip(), ""]
        if misses:
            lines += [
                "| Lead | Tags | Expected | Got | Confidence | Model summary |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
            for r in misses:
                summary = (r.get("summary") or "").replace("|", "/")[:140]
                lines.append(
                    f"| {r['id']} | {', '.join(r['tags'][:3])} | {r['expected_category']} / {r['expected_routing']} | "
                    f"{r['category']} / {r['routing']} | {r['confidence']} | {summary} |"
                )
        else:
            lines.append("No misses.")
        lines.append("")
    lines += [
        "## Spend",
        "",
        f"Ledger total for live evals: **${ledger['total_usd']:.4f}** of a ${ledger['budget_usd']:.2f} budget "
        f"(`evals/spend_ledger.json`, {len(ledger['runs'])} run entries).",
        "",
        "## Caveats",
        "",
        "- The sample set was written alongside the rules engine, so mock accuracy on it is a pipeline check, "
        "not a benchmark. The holdout set is the honest measure.",
        "- 70 leads is a small eval: one lead is 1.4 to 3.3 percentage points. Treat differences under about "
        "5 points as noise.",
        "- Routing labels encode one business's judgement of hot, warm and cold; scores near a threshold can "
        "reasonably land either side.",
        "",
    ]
    return "\n".join(lines)


def update_readme(tag: str) -> None:
    runs = load_runs()
    start, end = "<!-- results:start -->", "<!-- results:end -->"
    text = README.read_text()
    if start not in text or end not in text:
        return
    block = "\n".join([start, *results_table(runs, tag), end])
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    README.write_text(before + block + after)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", choices=list(CONFIGS), default=None)
    parser.add_argument("--data", nargs="+", choices=list(DATASETS), default=["sample", "holdout"])
    parser.add_argument("--matrix", action="store_true", help="run the 3 live configs, then build the report")
    parser.add_argument("--report", action="store_true", help="rebuild results.md and the README table only")
    parser.add_argument("--tag", default=os.getenv("PROMPT_TAG", "v1"), help="prompt version label for this run")
    parser.add_argument("--compare", default=None, help="earlier tag to show before/after against --tag")
    parser.add_argument("--budget", type=float, default=2.0)
    parser.add_argument("--stop-at", type=float, default=1.8, help="never let the ledger pass this many USD")
    parser.add_argument("--min-category-accuracy", type=float, default=0.0, help="exit 1 below this on 'sample'")
    args = parser.parse_args()

    if args.matrix:
        for config, datasets in MATRIX:
            run = run_config(config, datasets, args.tag, args.stop_at, args.budget)
            if run["stopped_for_budget"]:
                break
    elif args.config:
        run = run_config(args.config, args.data, args.tag, args.stop_at, args.budget)
        sample = run["datasets"].get("sample", {}).get("summary")
        if sample and sample["category_correct"] / max(sample["leads"], 1) < args.min_category_accuracy:
            print(f"category accuracy on sample below {args.min_category_accuracy}", file=sys.stderr)
            RESULTS.write_text(build_report(args.tag, args.compare))
            return 1
    RESULTS.write_text(build_report(args.tag, args.compare))
    update_readme(args.tag)
    print(f"wrote {RESULTS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
