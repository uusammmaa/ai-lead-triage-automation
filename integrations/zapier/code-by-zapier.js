// Code by Zapier (Run JavaScript) step: turns the /triage response into
// ready-to-use fields for Paths, Google Sheets, Slack and Gmail.
//
// Input Data keys to map in the Zapier editor (left side = key, right side =
// field from the "POST to /triage" step):
//   routing, lead_score, category, urgency, budget_signal, summary,
//   suggested_reply, score_reasons, email_type, domain, lead_id, mode,
//   lead_name, lead_email, lead_company, lead_source
//
// Paste everything below into the code box. Zapier passes every input as a
// string, so numbers and lists are parsed here.

const ROUTES = {
  hot: { log: true, alert: true, draft: true },
  warm: { log: true, alert: false, draft: true },
  cold: { log: true, alert: false, draft: false },
  discard: { log: false, alert: false, draft: false },
};

function clean(value) {
  return value === undefined || value === null ? "" : String(value).trim();
}

// Slack treats <, > and & as control characters (mentions, links).
function slackSafe(value) {
  return clean(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function mapTriage(input) {
  const routing = clean(input.routing).toLowerCase();
  const route = ROUTES[routing] || ROUTES.cold; // unknown value: log it, alert nobody
  const score = Number.parseInt(clean(input.lead_score), 10) || 0;
  const name = clean(input.lead_name);
  const company = clean(input.lead_company);
  const who = company ? `${name} (${company})` : name;

  return {
    routing: ROUTES[routing] ? routing : "cold",
    lead_score: score,
    should_log: route.log,
    is_hot: route.alert,
    needs_draft: route.draft,
    received_at: new Date().toISOString(),
    lead_id: clean(input.lead_id),
    lead_name: name,
    lead_email: clean(input.lead_email),
    lead_company: company,
    lead_source: clean(input.lead_source) || "zapier",
    category: clean(input.category),
    urgency: clean(input.urgency),
    budget_signal: clean(input.budget_signal),
    summary: clean(input.summary),
    email_type: clean(input.email_type),
    domain: clean(input.domain),
    score_reasons_text: clean(input.score_reasons),
    triage_mode: clean(input.mode),
    slack_text:
      `:fire: *Hot lead* from ${slackSafe(who)}\n` +
      `*Score:* ${score}/100 | *Urgency:* ${slackSafe(input.urgency)} | *Budget:* ${slackSafe(input.budget_signal)}\n` +
      `*Summary:* ${slackSafe(input.summary)}\n` +
      `${slackSafe(input.lead_email)} | draft reply saved in Gmail`,
    draft_subject: "Thanks for getting in touch",
    draft_body: clean(input.suggested_reply),
  };
}

return mapTriage(inputData);
