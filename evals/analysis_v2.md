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
