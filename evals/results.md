# Eval results

Datasets: `data/sample_leads.json` (30 leads, written with the rules) and `data/holdout_leads.json` (40 hard leads written later: German, Urdu, Arabic, one-liners, long rambling messages, recruiters, partnerships disguised as sales, 3 new injection styles).

> **Live runs have not been executed yet.** Only mock mode (the offline rules engine) is shown. Run `python evals/run_evals.py --matrix` with `ANTHROPIC_API_KEY` set to fill in the model rows.

## Results (prompt `v1`)

| Config | Dataset | Category acc. | Routing acc. | Injection resisted | Escalation rate | Skipped by pre-filter | p50 / p95 latency | Cost per 1,000 leads |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Mock (rules engine) | sample | 100% (30/30) | 100% (30/30) | 2/2 | n/a | 5 of 30 | 1 / 2 ms | $0.00 |
| Mock (rules engine) | holdout | 45% (18/40) | 58% (23/40) | 3/3 | n/a | 0 of 40 | 1 / 3 ms | $0.00 |

Cost per 1,000 leads is measured from API-reported token usage (cache reads and writes priced separately) and includes leads the pre-filter skipped at $0. Latency is wall-clock per lead, sequential.

## Confusion matrix: Mock (rules engine) (sample + holdout, 70 leads)

| expected \ predicted | sales_inquiry | support | partnership | job_seeker | spam | other |
| --- | --- | --- | --- | --- | --- | --- |
| sales_inquiry | **20** | 3 | . | . | . | 5 |
| support | . | **7** | . | . | . | 3 |
| partnership | 2 | . | **4** | . | . | 1 |
| job_seeker | 1 | . | . | **5** | . | 1 |
| spam | . | 1 | 1 | 1 | **6** | 2 |
| other | 1 | . | . | . | . | **6** |

## What Mock (rules engine) gets wrong (23 of 70)

| Lead | Tags | Expected | Got | Confidence | Model summary |
| --- | --- | --- | --- | --- | --- |
| H01 | german, hot_sales | sales_inquiry / hot | sales_inquiry / warm | None | Sales inquiry from Lena Brandt (Kranich Logistik GmbH) mentioning budget, with low urgency and budget mentioned. |
| H02 | urdu, hot_sales | sales_inquiry / hot | other / cold | None | General enquiry from Imran Qureshi (Zarlink Textiles), with low urgency and no budget stated. |
| H03 | long_rambling, hot_sales | sales_inquiry / hot | support / cold | None | Support request from Gareth Pryce (Oakmere Lettings) mentioning stopped, with low urgency and no budget stated. |
| H04 | vague_budget, hot_sales | sales_inquiry / hot | support / cold | None | Support request from Priyanka Desai (Lumora Events) mentioning issue, with low urgency and no budget stated. |
| H07 | arabic, warm_sales | sales_inquiry / warm | other / cold | None | General enquiry from Omar Haddad (Rimal Real Estate), with low urgency and no budget stated. |
| H08 | vague_budget, warm_sales | sales_inquiry / warm | other / cold | None | General enquiry from Felix Hartmann (Vantor Insurance), with low urgency and budget mentioned. |
| H09 | one_line, warm_sales | sales_inquiry / warm | other / cold | None | General enquiry from Ruth Adeyemi (Corvane Solar), with low urgency and no budget stated. |
| H10 | partnership_disguised_as_sales | partnership / warm | other / cold | None | General enquiry from Tobias Lindqvist (AppBazaar), with medium urgency and no budget stated. |
| H11 | partnership_disguised_as_sales | partnership / warm | sales_inquiry / warm | None | Sales inquiry from Chloe Barnard (Keystone AI Consulting) mentioning interested in, interested, a call, with low urgency and no budget state |
| H12 | long_rambling, warm_sales | sales_inquiry / warm | support / cold | None | Support request from Maureen Kelly (Kelly's Bakehouse) mentioning help, with low urgency and no budget stated. |
| H16 | press | other / cold | sales_inquiry / warm | None | Sales inquiry from Hannah Cole (The Business Desk) mentioning quote, with low urgency and no budget stated. |
| H18 | arabic, support | support / cold | other / cold | None | General enquiry from Layla Mansour (Rimal Real Estate), with low urgency and no budget stated. |
| H19 | urdu, roman_urdu, support | support / cold | other / cold | None | General enquiry from Bilal Ahmed (Zarlink Textiles), with low urgency and no budget stated. |
| H20 | support, upsell_hint | support / cold | other / cold | None | General enquiry from Sara Lindgren (Pollen Skincare), with low urgency and no budget stated. |
| H23 | german, job_seeker | job_seeker / cold | other / cold | None | General enquiry from Mia Schröder, with low urgency and no budget stated. |
| H24 | job_seeker, freelancer, ambiguous | job_seeker / cold | sales_inquiry / hot | None | Sales inquiry from Ravi Shankar mentioning build, with high urgency and an explicit budget. |
| H26 | vendor_pitch, spam | spam / discard | other / warm | None | General enquiry from Vikram Rao (CodeShore Teams), with low urgency and an explicit budget. |
| H27 | recruiter, vendor_pitch, spam | spam / discard | job_seeker / cold | None | Job application from Ellie Shaw (TalentPeak Recruiting) mentioning join your team, with low urgency and no budget stated. |
| H28 | personalised_spam, spam | spam / discard | support / cold | None | Support request from Jordan Blake (PipelinePro) mentioning help, with high urgency and no budget stated. |
| H30 | one_line, gibberish, spam | spam / discard | other / cold | None | General enquiry from xx, with low urgency and no budget stated. |
| H34 | partnership, ambiguous | partnership / cold | sales_inquiry / cold | None | Sales inquiry from Marcus Webb mentioning interested in, interested, with low urgency and no budget stated. |
| H39 | spam, disguised_as_partnership | spam / discard | partnership / hot | None | Partnership proposal from Content Team (LuckySpin Media) mentioning partnership, with low urgency and an explicit budget. |
| H40 | german, one_line, warm_sales | sales_inquiry / warm | other / cold | None | General enquiry from Stefan Huber (Alpenblick Hotels), with low urgency and no budget stated. |

## Spend

Ledger total for live evals: **$0.0000** of a $2.00 budget (`evals/spend_ledger.json`, 0 run entries).

## Caveats

- The sample set was written alongside the rules engine, so mock accuracy on it is a pipeline check, not a benchmark. The holdout set is the honest measure.
- 70 leads is a small eval: one lead is 1.4 to 3.3 percentage points. Treat differences under about 5 points as noise.
- Routing labels encode one business's judgement of hot, warm and cold; scores near a threshold can reasonably land either side.
