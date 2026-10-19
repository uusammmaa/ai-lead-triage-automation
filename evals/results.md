# Eval results

Run: 2026-10-19T09:59:27+00:00 | mode: **mock** | leads: 30 | modes seen: {'mock': 30}

| Metric | Value |
| --- | --- |
| Category accuracy | 100.0% (30/30) |
| Routing accuracy | 100.0% (30/30) |
| Prompt injection resisted | 2/2 |
| Avg latency | 0.3 ms |
| p95 latency | 1 ms |
| Measured cost per 1,000 leads | $0.00 |
| Projected live cost per 1,000 leads (`claude-sonnet-5-5`) | $10.31 |

## Per category

| Category | Leads | Correct |
| --- | --- | --- |
| job_seeker | 3 | 3 |
| other | 2 | 2 |
| partnership | 3 | 3 |
| sales_inquiry | 12 | 12 |
| spam | 5 | 5 |
| support | 5 | 5 |

## Misses

None.

## How to read this

- **Mock mode** runs the deterministic rules engine. Its keyword lists were written alongside this
  dataset, so a high mock score proves the pipeline, schema and routing work end to end. It is not a
  benchmark of the AI. Run `--mode live` with an API key for the model's real numbers.
- **Measured cost** comes from real token usage reported by the API. It is $0 in mock mode.
- **Projected live cost** estimates a typical 2-call agent run per lead (about 2,304 input and
  570 output tokens, 4 characters per token, no prompt caching) at list
  prices. Prompt caching of the system prompt and tools lowers the real figure.
- Latency in mock mode is local CPU time. Live latency is dominated by the model call.
