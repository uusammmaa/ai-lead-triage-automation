# Make (formerly Integromat) delivery option

```
Custom webhook ─> HTTP: POST /triage ─> Router ─┬─ filter: routing is not discard ─> Google Sheets: Add a Row
                                                ├─ filter: routing = hot          ─> Slack: Create a Message
                                                └─ filter: routing = hot or warm  ─> Gmail: Create a Draft
```

Two ways to build it: import `blueprint.json`, or follow the manual guide below (about 15 minutes).

## Honest status of the blueprint

`blueprint.json` follows Make's export format (`flow`, `routes`, `filter`, `metadata`), but **it has not been imported into a Make account**, because Make has no local runtime to test against. Module identifiers and field names (`gateway:CustomWebHook`, `http:ActionSendData`, `builtin:BasicRouter`, `google-sheets:addRow`, `slack:CreateMessage`, `google-email:ActionCreateDraft`) are written from Make's public blueprint conventions and may differ by module version. If the import complains, or a module shows up empty, build that module by hand with the guide below. The filters and mappings in the guide are the same as in the blueprint.

### Importing

1. **Scenarios > Create a new scenario > ... (more) > Import Blueprint**, choose `blueprint.json`.
2. Open each module and connect your accounts (Google, Slack). Blueprints never contain credentials.
3. **Webhook module**: click *Add*, name it `lead-triage`, open *Show advanced settings*, set **JSON pass-through = Yes**, save, copy the URL.
4. **HTTP module**: set the URL to `https://<your-core>/triage` and the `X-API-Key` header value.
5. **Google Sheets**: pick your spreadsheet and the `Leads` sheet. **Slack**: pick the channel.
6. Run once, send a test lead, then switch the scenario **ON** (instant trigger).

## Manual build guide

### Before you start

- The core is deployed with a public HTTPS URL and you have one of its `API_KEYS`.
- A Google Sheet with a `Leads` tab and this header row (columns A to Q):
  `received_at, lead_id, name, email, company, source, category, lead_score, routing, urgency, budget_signal, summary, email_type, domain, score_reasons, suggested_reply, triage_mode`

### Module 1. Webhooks > Custom webhook

1. Add **Webhooks > Custom webhook**, click *Add*, name it `lead-triage`.
2. *Show advanced settings* > **JSON pass-through: Yes**. This forwards the exact JSON the form sent, so quotes and line breaks in a lead's message cannot break the request body.
3. Save and copy the webhook URL. Click *Run once* and send a test lead (from `form/index.html`, choosing *Make*, or with curl).

### Module 2. HTTP > Make a request

| Field | Value |
| --- | --- |
| URL | `https://<your-core>/triage` |
| Method | POST |
| Headers | `X-API-Key` = your core API key |
| Body type | Raw |
| Content type | JSON (application/json) |
| Request content | map `value` from module 1 |
| Parse response | Yes |
| Timeout | 60 |

Under advanced settings, **Evaluate all states as errors (except for 2xx and 3xx)**: Yes, so a 401 or 422 stops the run and shows up in the history.

Run once. Module 2's output now has `Data > routing`, `lead_score`, `summary`, `suggested_reply`, `enrichment`, `lead` and `meta`.

> No JSON pass-through option on your plan? Insert **JSON > Create JSON** between modules 1 and 2. Create a data structure with *Generator* from the sample `{"name":"","email":"","company":"","message":"","source":""}`, map the five webhook fields into it, and send its `JSON string` output as the request content. Make escapes the values for you.

### Module 3. Flow Control > Router

Add a Router after module 2 with three routes. Click the wrench on each route's line to set its filter. Operator: **Text operators > Equal to** (or *Not equal to*), case insensitive.

| Route | Filter label | Condition |
| --- | --- | --- |
| 1 | Every lead except discard | `2. Data: routing` *Not equal to* `discard` |
| 2 | Hot leads only | `2. Data: routing` *Equal to* `hot` |
| 3 | Hot or warm | `2. Data: routing` *Equal to* `hot` **OR** `2. Data: routing` *Equal to* `warm` |

### Route 1. Google Sheets > Add a Row

Spreadsheet: yours. Sheet: `Leads`. Table contains headers: Yes. Value input option: **Raw** (so lead text is never evaluated as a formula). Map:

| Column | Value |
| --- | --- |
| received_at | `formatDate(now; "YYYY-MM-DDTHH:mm:ssZ")` |
| lead_id | `2. Data: meta: lead_id` |
| name / email / source | `2. Data: lead: name` / `email` / `source` |
| company | `ifempty(2. Data: lead: company; 2. Data: enrichment: company_guess)` |
| category, lead_score, routing, urgency, budget_signal, summary, suggested_reply | same-named fields under `2. Data` |
| email_type / domain | `2. Data: enrichment: email_type` / `domain` |
| score_reasons | `join(2. Data: score_reasons; "; ")` |
| triage_mode | `2. Data: meta: mode` |

### Route 2. Slack > Create a Message

Channel type: public channel, pick your sales channel. Text:

```
:fire: *Hot lead* from {{2.data.lead.name}} ({{2.data.lead.company}})
*Score:* {{2.data.lead_score}}/100 | *Urgency:* {{2.data.urgency}} | *Budget:* {{2.data.budget_signal}}
*Summary:* {{2.data.summary}}
{{2.data.lead.email}} | draft reply saved in Gmail
```

Wrap the name and summary in `replace(...; "<"; "")` and `replace(...; ">"; "")` (as the blueprint does) so lead text cannot trigger `@channel`.

### Route 3. Gmail > Create a Draft

To: `2. Data: lead: email`. Subject: `Thanks for getting in touch`. Content: `2. Data: suggested_reply` (if the body type is HTML, wrap it in `replace(...; newline; "<br>")`). The draft waits for a human to review and send.

### Error handling (recommended)

Right-click module 2 > **Add error handler > Break**, with 3 attempts every 1 minute. Enable *Allow storing of incomplete executions* in scenario settings so failed leads can be replayed once the core is back.

## Running costs

Make bills operations per module run: webhook 1, HTTP 1, router 0, plus 1 per route that passes its filter. That is 5 operations for a hot lead, 4 for warm, 3 for cold and 2 for discard. Check Make's current pricing rules before quoting a client.
