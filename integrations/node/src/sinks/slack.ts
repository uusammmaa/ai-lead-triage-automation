import { checkResponse, fetchWithTimeout } from "../retry.js";
import type { Lead, TriageResult } from "../types.js";
import type { AlertSink } from "./types.js";

/** Escape Slack control characters so lead text cannot ping @channel or inject links. */
export function slackEscape(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function slackPayload(lead: Lead, result: TriageResult) {
  const who = slackEscape(lead.company ? `${lead.name} (${lead.company})` : lead.name);
  return {
    text: `Hot lead: ${who}, score ${result.lead_score}`,
    blocks: [
      { type: "header", text: { type: "plain_text", text: `Hot lead: ${lead.name}`.slice(0, 150) } },
      {
        type: "section",
        fields: [
          { type: "mrkdwn", text: `*From*\n${who}` },
          { type: "mrkdwn", text: `*Score*\n${result.lead_score}/100` },
          { type: "mrkdwn", text: `*Urgency*\n${result.urgency}` },
          { type: "mrkdwn", text: `*Budget*\n${result.budget_signal}` },
        ],
      },
      { type: "section", text: { type: "mrkdwn", text: `*Summary*\n${slackEscape(result.summary)}` } },
      {
        type: "context",
        elements: [
          {
            type: "mrkdwn",
            text: `${slackEscape(lead.email)} | ${result.enrichment.email_type} email | draft reply saved in Gmail`,
          },
        ],
      },
    ],
  };
}

export class SlackWebhookAlertSink implements AlertSink {
  readonly name = "slack";

  constructor(
    private readonly webhookUrl: string,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  async alert(lead: Lead, result: TriageResult): Promise<void> {
    const res = await fetchWithTimeout(
      this.fetchImpl,
      this.webhookUrl,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(slackPayload(lead, result)) },
      10_000,
    );
    await checkResponse(res, "slack webhook");
  }
}
