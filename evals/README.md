# Evals

Two labelled sets, four configurations, one hard spend cap.

| Set | Leads | Purpose |
| --- | --- | --- |
| `data/sample_leads.json` | 30 | Written alongside the rules engine. A pipeline check, not a benchmark. |
| `data/holdout_leads.json` | 40 | Written later to be hard: German, Urdu (script and Roman), Arabic, one-liners, long rambling messages, vague budget hints, recruiters, partnerships disguised as sales, and three new injection styles (signature, fake system message, JSON in the body). |

| Config | Primary model | Escalation |
| --- | --- | --- |
| `mock` | none (rules engine) | none |
| `haiku` | `claude-haiku-5-5` | none |
| `haiku_escalation` (default) | `claude-haiku-5-5` | `claude-sonnet-5-5` when confidence < 0.6 or output fails validation twice |
| `sonnet` | `claude-sonnet-5-5` | none |

## Run

```bash
# Offline, free (this is what CI runs)
python evals/run_evals.py --config mock --data sample holdout

# Live: the three model configs (Sonnet on the holdout only), then the report
export ANTHROPIC_API_KEY=...
python evals/run_evals.py --matrix
```

Outputs: `evals/results.md` (table, confusion matrix for the default config, misses), the table between the `results` markers in the root README, one JSON file per run in `evals/runs/`, and `evals/spend_ledger.json`.

## Spend cap

Every live run appends its measured cost (from API-reported usage, cache reads and writes priced separately) to `evals/spend_ledger.json`. Before each lead the runner checks that the ledger total plus a worst-case reserve for that lead stays under `--stop-at` (default $1.80 against a $2.00 budget) and stops cleanly if not, marking the run partial. Delete the ledger only when starting a new budget.

Expected spend for `--matrix`, from token estimates: about $0.05 for Haiku, $0.20 to $0.35 for Haiku with escalation, $0.50 to $0.70 for Sonnet on the holdout. About $1 in total, leaving room for one prompt revision.

## One prompt revision, then stop

The rule for this project: if Haiku is weak somewhere, change the prompt or the few-shot examples **once**, re-run, and report before and after. No tuning towards 100%.

```bash
# 1. After --matrix (prompt tag v1), read the misses in evals/results.md
# 2. Edit core/app/agent.py (SYSTEM_PROMPT) or core/app/fewshots.py, once
# 3. Re-run the Haiku configs under a new tag
python evals/run_evals.py --config haiku --data sample holdout --tag v2
python evals/run_evals.py --config haiku_escalation --data sample holdout --tag v2
# 4. Rebuild the report with a before/after table
python evals/run_evals.py --report --tag v2 --compare v1
```

Write the human analysis of misses to `evals/analysis_<tag>.md`; the report includes it above the misses table.

## Caveats

- 70 leads is small: one lead is 1.4 to 3.3 points. Differences under about 5 points are noise.
- Routing labels reflect one business's view of hot, warm and cold. Leads scored near a threshold can land either side legitimately.
- The holdout was written by the same author as the rules and prompt, after them and without consulting the keyword lists. It is harder than the sample, not truly independent.
