# Custom Node.js / TypeScript worker

For clients who want plain code they own, with no automation platform fee.

```
POST /webhook/lead  ->  core POST /triage  ->  Google Sheets (hot, warm, cold)
                                            ->  Slack alert   (hot)
                                            ->  Gmail draft   (hot, warm)
```

## Run it

```bash
npm install
npm test              # 41 vitest tests, no credentials needed
npm run build
CORE_URL=http://localhost:8000 CORE_API_KEY=dev-key-change-me npm start
```

Send a lead:

```bash
curl -X POST http://localhost:3000/webhook/lead \
  -H 'Content-Type: application/json' \
  -d '{"name":"Dana Whitfield","email":"dana@brightpath-logistics.example.com","company":"Brightpath Logistics","message":"Budget $15k, need lead triage within two weeks.","source":"webform"}'
```

Without credentials every destination uses a console adapter, so the whole flow runs and logs what it would have done.

## Environment

| Variable | Purpose |
| --- | --- |
| `PORT` | Listen port, default 3000 |
| `CORE_URL` / `CORE_API_KEY` | Where the Python core runs, and its `X-API-Key` |
| `WEBHOOK_SECRET` | Optional. If set, callers must send `X-Webhook-Secret` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REFRESH_TOKEN` | OAuth client and refresh token for the mailbox that owns the sheet and the drafts. Scopes: `spreadsheets`, `gmail.compose` |
| `SHEETS_SPREADSHEET_ID` / `SHEETS_RANGE` | Target sheet, default range `Leads!A1` |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook for hot lead alerts |
| `DRAFT_SUBJECT` | Subject line for Gmail drafts |

Sheet header row (row 1 of the `Leads` tab) in this order:
`received_at, lead_id, name, email, company, source, category, lead_score, routing, urgency, budget_signal, summary, email_type, domain, score_reasons, suggested_reply, triage_mode`

## Reliability

- **Idempotency.** Each lead gets a hash of its normalised email and message (identical to the core's `meta.lead_id`). A redelivered lead is not triaged or routed twice. Concurrent duplicates collapse into one run.
- **Partial failure.** Destinations run independently. If Slack fails but the sheet succeeded, the worker returns 502, and on redelivery only Slack runs again.
- **Retry with backoff.** Exponential backoff with jitter on network errors, timeouts, 429 and 5xx, honouring `Retry-After`. Permanent 4xx errors fail fast.
- **Safe output.** Sheet rows are written with `valueInputOption=RAW` so lead text cannot become a spreadsheet formula. Slack text is escaped so a lead cannot trigger `@channel`. Email headers are stripped of line breaks.

## Swapping a destination

Each destination is an interface in `src/sinks/types.ts` (`CrmSink`, `AlertSink`, `DraftSink`). To move from Google Sheets to HubSpot, add a `HubSpotCrmSink` that implements `appendLead()` and select it in `src/config.ts`. Nothing else changes.

The idempotency store is in memory. For more than one worker instance, implement `IdempotencyStore` on Redis or Postgres.
