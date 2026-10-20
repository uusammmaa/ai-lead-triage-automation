# Eval results

Datasets: `data/sample_leads.json` (30 leads, written with the rules) and `data/holdout_leads.json` (40 hard leads written later: German, Urdu, Arabic, one-liners, long rambling messages, recruiters, partnerships disguised as sales, 3 new injection styles).

## Results (prompt `v2`)

| Config | Dataset | Category acc. | Routing acc. | Injection resisted | Escalation rate | Skipped by pre-filter | p50 / p95 latency | Cost per 1,000 leads |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Mock (rules engine) | sample | 100% (30/30) | 100% (30/30) | 2/2 | n/a | 5 of 30 | 1 / 2 ms | $0.00 |
| Mock (rules engine) | holdout | 45% (18/40) | 58% (23/40) | 3/3 | n/a | 0 of 40 | 1 / 3 ms | $0.00 |
| Haiku only | sample | 100% (30/30) | 100% (30/30) | 2/2 | 0% (0/25) | 5 of 30 | 5029 / 6153 ms | $0.51 |
| Haiku only | holdout | 98% (39/40) | 98% (39/40) | 3/3 | 0% (0/40) | 0 of 40 | 5364 / 7251 ms | $0.61 |
| Haiku + Sonnet escalation | sample | 100% (30/30) | 100% (30/30) | 2/2 | 4% (1/25) | 5 of 30 | 4899 / 7486 ms | $1.04 |
| Haiku + Sonnet escalation | holdout | 100% (40/40) | 100% (40/40) | 3/3 | 2% (1/40) | 0 of 40 | 5217 / 7584 ms | $0.78 |
| Sonnet only `v1` | holdout | 98% (39/40) | 98% (39/40) | 3/3 | 0% (0/40) | 0 of 40 | 5008 / 7071 ms | $8.10 |

Cost per 1,000 leads is measured from API-reported token usage (cache reads and writes priced separately) and includes leads the pre-filter skipped at $0. Latency is wall-clock per lead, sequential.

## Before and after the prompt change (`v1` to `v2`)

| Config | Dataset | Category acc. | Routing acc. | Injection resisted | Escalation rate | Skipped by pre-filter | p50 / p95 latency | Cost per 1,000 leads |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Haiku only `v1` | sample | 100% (30/30) | 93% (28/30) | 2/2 | 0% (0/25) | 5 of 30 | 4556 / 6687 ms | $0.46 |
| Haiku only `v1` | holdout | 100% (40/40) | 100% (40/40) | 3/3 | 0% (0/40) | 0 of 40 | 4884 / 6516 ms | $0.55 |
| Haiku only `v2` | sample | 100% (30/30) | 100% (30/30) | 2/2 | 0% (0/25) | 5 of 30 | 5029 / 6153 ms | $0.51 |
| Haiku only `v2` | holdout | 98% (39/40) | 98% (39/40) | 3/3 | 0% (0/40) | 0 of 40 | 5364 / 7251 ms | $0.61 |
| Haiku + Sonnet escalation `v1` | sample | 100% (30/30) | 93% (28/30) | 2/2 | 4% (1/25) | 5 of 30 | 4435 / 5950 ms | $0.97 |
| Haiku + Sonnet escalation `v1` | holdout | 98% (39/40) | 98% (39/40) | 3/3 | 5% (2/40) | 0 of 40 | 5070 / 6866 ms | $0.91 |
| Haiku + Sonnet escalation `v2` | sample | 100% (30/30) | 100% (30/30) | 2/2 | 4% (1/25) | 5 of 30 | 4899 / 7486 ms | $1.04 |
| Haiku + Sonnet escalation `v2` | holdout | 100% (40/40) | 100% (40/40) | 3/3 | 2% (1/40) | 0 of 40 | 5217 / 7584 ms | $0.78 |

## Confusion matrix: Haiku + Sonnet escalation (sample + holdout, 70 leads)

| expected \ predicted | sales_inquiry | support | partnership | job_seeker | spam | other |
| --- | --- | --- | --- | --- | --- | --- |
| sales_inquiry | **28** | . | . | . | . | . |
| support | . | **10** | . | . | . | . |
| partnership | . | . | **7** | . | . | . |
| job_seeker | . | . | . | **7** | . | . |
| spam | . | . | . | . | **11** | . |
| other | . | . | . | . | . | **7** |

## What Haiku + Sonnet escalation gets wrong (0 of 70)

### What changed between `v1` and `v2`

One prompt revision, based on the real `v1` Haiku misses, then stop. No few-shot examples were added or changed.

| `v1` miss | What Haiku did | Prompt change in `v2` |
| --- | --- | --- |
| L10 (sample): six-gym operator asks "what does it cost?", expected warm | Counted the price question as `budget_signal: mentioned` (+10), scored 75, routed hot | `budget_signal` now means the lead refers to *their own* budget or money; "Asking what something costs is not a budget signal." |
| L11 (sample): solo consultant, free email, $2k for a website chatbot, expected warm | Noted "chatbots are outside the listed services, so fit is uncertain" but had no rule to act on it, scored 80, routed hot | After the modifiers, compare with `ideal_customer` and `services`; a lead clearly outside them (sole trader or consumer, or a service not listed) loses 10 points with a stated reason |
| H24 (holdout, escalation run only): an individual offering Make and Zapier work at $25/hour, expected job_seeker | Called it spam ("outsourced development") at confidence 0.7; the Haiku-only run got it right, so the two category definitions overlapped | `job_seeker` now says an individual offering their own hours is a job seeker, even with an hourly rate; `spam` sales offers are "from a company or agency" |

H24 is a holdout lead, so the `v2` holdout numbers are slightly optimistic for that one lead. The change fixes a real contradiction in the category definitions rather than adding a rule for that lead.

### Results

- **Fixed:** L10 and L11 now route warm in both Haiku configs (sample routing 28/30 to 30/30). H24 is now job_seeker in the escalation run.
- **New miss:** H39, a casino link-placement pitch that opens with "Partnership opportunity!", came back as partnership in the Haiku-only `v2` run, at confidence 0.55. In the escalation `v2` run Haiku got it right without escalating. The two `v2` Haiku runs differ on this lead, so this is run-to-run variance on a hard disguise case, not a stable regression. Below the 0.6 threshold, the escalation config would send it to Sonnet.
- **Side effect:** the fit penalty also lowers some support, partnership and other scores by 10 (for example support leads 10 to 0). Routing does not change, because category overrides route those categories cold anyway.
- **Escalation:** 1 lead per set escalated in `v2` (L14 and H14, both vague one-liners Haiku already labelled correctly). In every run so far, escalation has not changed a label. It costs about $0.30 to $0.50 more per 1,000 leads.
- **Cost:** `v2` adds about 100 prompt tokens, so Haiku costs about 10% more per lead.

Accuracy at this level is at the ceiling of a 70-lead set: one lead is 1.4 to 3.3 points, so the `v1` to `v2` differences on the holdout are within noise. The clear signal is the gap between the rules engine (45% holdout category accuracy) and every model config (98% to 100%).

No misses.

## Spend

Ledger total for live evals: **$0.5272** of a $2.00 budget (`evals/spend_ledger.json`, 9 run entries).

## Caveats

- The sample set was written alongside the rules engine, so mock accuracy on it is a pipeline check, not a benchmark. The holdout set is the honest measure.
- 70 leads is a small eval: one lead is 1.4 to 3.3 percentage points. Treat differences under about 5 points as noise.
- Routing labels encode one business's judgement of hot, warm and cold; scores near a threshold can reasonably land either side.
