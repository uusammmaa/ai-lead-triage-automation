# n8n delivery option

`lead-triage.workflow.json` is an importable n8n workflow (built and tested on n8n 2.43.8).

```
Lead Webhook ─┐
              ├─> Lead ─> AI Triage (core /triage) ─> Combine Lead + Triage ─┬─> Came from webhook? ─> Respond with Triage
Gmail Trigger ┘   (disabled by default)                                      └─> Route by Score
                                                                                   hot     -> Sheet, Slack, Gmail draft
                                                                                   warm    -> Sheet, Gmail draft
                                                                                   cold    -> Sheet
                                                                                   discard -> nothing
```

## Import (5 minutes)

1. In n8n: **Workflows > Add workflow > ... menu > Import from File**, pick `lead-triage.workflow.json`.
   CLI alternative: `n8n import:workflow --input=lead-triage.workflow.json`.
2. Create four credentials and select them on the nodes that show a red warning:

   | Node | Credential type | Settings |
   | --- | --- | --- |
   | AI Triage (core /triage) | Header Auth | Name `X-API-Key`, Value = one of the core's `API_KEYS` |
   | Log to CRM Sheet | Google Sheets OAuth2 | Google account that owns the sheet |
   | Slack Hot Lead Alert | Slack API | Bot token with `chat:write`, bot invited to the channel |
   | Create Gmail Draft / Gmail Trigger | Gmail OAuth2 | The mailbox that should hold the drafts |

3. **AI Triage**: set the URL. `http://core:8000/triage` works inside the provided `docker-compose.yml`; otherwise use your deployed core URL.
4. **Log to CRM Sheet**: replace `REPLACE_WITH_SPREADSHEET_ID` with your sheet ID (the long string in the sheet URL). Create a tab called `Leads` with this header row:
   `received_at, lead_id, name, email, company, source, category, lead_score, routing, urgency, budget_signal, summary, email_type, domain, score_reasons, suggested_reply, triage_mode`
5. **Slack Hot Lead Alert**: change `#sales-leads` to your channel.
6. Save, then click **Publish** (or toggle Active on older versions). Copy the production webhook URL from the **Lead Webhook** node: `https://<your-n8n>/webhook/lead-triage`.
7. Optional: enable **Gmail Trigger (optional)** to triage unread inbound emails as well as form posts.

## Test it

```bash
curl -X POST https://<your-n8n>/webhook/lead-triage \
  -H 'Content-Type: application/json' \
  -d '{"name":"Dana Whitfield","email":"dana@brightpath-logistics.example.com","company":"Brightpath Logistics","message":"Budget $15k, we need lead triage within two weeks.","source":"webform"}'
```

The webhook answers with the triage result (category, score, routing, summary, suggested reply), and the routing branch runs in the same execution.

## What was verified, and what was not

Verified on n8n 2.43.8 in Docker against the real core: the file imports, publishes, the webhook returns the triage JSON, and the Switch sends hot leads to Sheet + Slack + Gmail, warm leads to Sheet + Gmail and spam to the discard branch.

Not verified: the Google Sheets, Slack and Gmail nodes against real accounts (they need your credentials). Their parameters were checked against the node definitions shipped with n8n 2.43.8, but run one test lead per branch after connecting credentials.

## Design notes

- **One shared path for every entry point.** The webhook and the Gmail trigger both map into the same `Lead` fields, so the triage call and routing exist once.
- **Retries.** The HTTP node retries 3 times with a 2 second wait. If the core is down for longer, the execution fails and shows in n8n's execution log; the core itself degrades to its rules engine when the Claude API is unavailable, so a lead is not lost because of an AI outage.
- **Respond only to webhooks.** The `Came from webhook?` check stops the Gmail path from trying to answer an HTTP request that does not exist.
- **Slack safety.** Lead text has `<`, `>` and `&` stripped before it is posted, so a lead cannot trigger `@channel` mentions.
