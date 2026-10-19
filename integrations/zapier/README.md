# Zapier delivery option

Zapier has no importable file format for Zaps, so this is a click-by-click build. It takes about 10 minutes.

```
1. Webhooks by Zapier: Catch Hook          (lead arrives)
2. Webhooks by Zapier: POST                (call the AI core /triage)
3. Code by Zapier: Run JavaScript          (map the response, code-by-zapier.js)
4. Paths by Zapier
   A. should_log is true   -> Google Sheets: Create Spreadsheet Row
   B. is_hot is true       -> Slack: Send Channel Message
   C. needs_draft is true  -> Gmail: Create Draft
```

Routing result: **hot** runs A, B and C. **warm** runs A and C. **cold** runs A. **discard** runs nothing. Zapier runs every path whose rule matches, so one lead can go down several paths.

## Before you start

- The core is deployed and reachable from the internet (Zapier cannot call `localhost`). You need its URL and one value from its `API_KEYS`.
- A Google Sheet with a tab called `Leads` and this header row:
  `received_at, lead_id, name, email, company, source, category, lead_score, routing, urgency, budget_signal, summary, email_type, domain, score_reasons, suggested_reply, triage_mode`
- Paths needs a Zapier Professional plan or higher. On a lower plan, build three small Zaps that each repeat steps 1 to 3 and use a **Filter by Zapier** step instead of a path.

## Step 1. Trigger: Webhooks by Zapier, Catch Hook

1. Create a Zap. Trigger app **Webhooks by Zapier**, event **Catch Hook**. Leave *Pick off a Child Key* empty.
2. Copy the webhook URL Zapier shows (it looks like `https://hooks.zapier.com/hooks/catch/123/abc/`).
3. Send a test lead to it, either from `form/index.html` (choose *Zapier* and paste the URL) or:
   ```bash
   curl -X POST 'https://hooks.zapier.com/hooks/catch/123/abc/' \
     -H 'Content-Type: application/json' \
     -d '{"name":"Dana Whitfield","email":"dana@brightpath-logistics.example.com","company":"Brightpath Logistics","message":"Budget $15k, we need lead triage within two weeks.","source":"webform"}'
   ```
4. Click **Test trigger**. You should see `name`, `email`, `company`, `message`, `source`.

## Step 2. Action: Webhooks by Zapier, POST

| Field | Value |
| --- | --- |
| URL | `https://<your-core>/triage` |
| Payload Type | `json` |
| Data | `name` = *1. Name*, `email` = *1. Email*, `company` = *1. Company*, `message` = *1. Message*, `source` = *1. Source* |
| Wrap Request In Array | No |
| Unflatten | Yes |
| Headers | `X-API-Key` = your core API key |

Rename the step to **POST to /triage** and click **Test step**. The response shows `routing`, `lead_score`, `summary`, `suggested_reply`, `Enrichment Email Type`, `Lead Name`, `Lead Email` and the rest.

If `company` is blank in the test lead, Zapier sends an empty string. The core treats that as no company.

## Step 3. Action: Code by Zapier, Run JavaScript

1. Add **Code by Zapier**, event **Run JavaScript**.
2. In **Input Data**, add these keys and map each one from step 2:

   | Key | Map from step 2 |
   | --- | --- |
   | routing | Routing |
   | lead_score | Lead Score |
   | category | Category |
   | urgency | Urgency |
   | budget_signal | Budget Signal |
   | summary | Summary |
   | suggested_reply | Suggested Reply |
   | score_reasons | Score Reasons |
   | email_type | Enrichment Email Type |
   | domain | Enrichment Domain |
   | lead_id | Meta Lead Id |
   | mode | Meta Mode |
   | lead_name | Lead Name |
   | lead_email | Lead Email |
   | lead_company | Lead Company |
   | lead_source | Lead Source |

3. Paste the contents of [`code-by-zapier.js`](code-by-zapier.js) into **Code** and click **Test step**.
4. Output fields include `should_log`, `is_hot`, `needs_draft` (true or false), `slack_text`, `draft_subject`, `draft_body` and clean copies of every column.

## Step 4. Paths by Zapier

Add **Paths**, then build three paths. Each rule uses the Code step's output and the condition **(Boolean) Is true**.

### Path A: Log to CRM (rule: `should_log` is true)

Action **Google Sheets: Create Spreadsheet Row**. Pick the spreadsheet and the `Leads` worksheet, then map each column to the field with the same name from step 3 (`received_at`, `lead_id`, `lead_name` into *name*, `lead_email` into *email*, and so on). Map `score_reasons_text` into *score_reasons*, `draft_body` into *suggested_reply*, `triage_mode` into *triage_mode*.

### Path B: Hot lead alert (rule: `is_hot` is true)

Action **Slack: Send Channel Message**. Channel: your sales channel. Message Text: `slack_text`. Send as a bot: Yes. Include a link to this Zap: No.

### Path C: Draft reply (rule: `needs_draft` is true)

Action **Gmail: Create Draft**. To: `lead_email`. Subject: `draft_subject`. Body Type: Plain. Body: `draft_body`. The draft waits in the mailbox for a human to review and send.

## Step 5. Publish

Turn the Zap on. Point your website form (or `form/index.html`) at the Catch Hook URL.

## Running costs

Zapier bills tasks for action steps; the trigger, Filter and Paths steps are free at the time of writing. That makes the POST and Code steps 2 tasks, plus 1 per path that runs: 5 tasks for a hot lead, 4 for warm, 3 for cold and 2 for discard. Budget roughly 3 to 4 tasks per lead when choosing a plan, and check Zapier's current task rules before quoting a client.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| POST step returns 401 | The `X-API-Key` header is missing or does not match the core's `API_KEYS` |
| POST step returns 422 | A required field is empty (name, email or message), or the email is not valid |
| POST step returns 429 | The core's per-key rate limit was hit; raise `RATE_LIMIT_PER_MINUTE` |
| A path never runs | Check the rule uses *(Boolean) Is true*, not *(Text) Exactly matches* |
| Slack message shows `&lt;` | Expected when a lead typed `<`; it is escaped so leads cannot ping the channel |
