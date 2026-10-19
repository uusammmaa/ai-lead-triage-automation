import type { Lead, TriageResult } from "../types.js";
import type { AlertSink, CrmSink, DraftSink } from "./types.js";
import { crmRow } from "./types.js";

type Logger = (event: string, data: Record<string, unknown>) => void;

export const jsonLogger: Logger = (event, data) => {
  console.log(JSON.stringify({ ts: new Date().toISOString(), event, ...data }));
};

/** Mock adapters: log what would have happened. Used when credentials are missing. */
export class ConsoleCrmSink implements CrmSink {
  readonly name = "console-crm";
  readonly rows: (string | number)[][] = [];
  constructor(private readonly log: Logger = jsonLogger) {}

  async appendLead(lead: Lead, result: TriageResult): Promise<void> {
    const row = crmRow(lead, result);
    this.rows.push(row);
    this.log("crm_append", { sink: this.name, lead_id: result.meta.lead_id, routing: result.routing });
  }
}

export class ConsoleAlertSink implements AlertSink {
  readonly name = "console-alert";
  readonly alerts: string[] = [];
  constructor(private readonly log: Logger = jsonLogger) {}

  async alert(lead: Lead, result: TriageResult): Promise<void> {
    this.alerts.push(result.meta.lead_id);
    this.log("hot_lead_alert", { sink: this.name, lead_id: result.meta.lead_id, score: result.lead_score });
  }
}

export class ConsoleDraftSink implements DraftSink {
  readonly name = "console-draft";
  readonly drafts: { to: string; body: string }[] = [];
  constructor(private readonly log: Logger = jsonLogger) {}

  async createDraft(lead: Lead, result: TriageResult): Promise<void> {
    this.drafts.push({ to: lead.email, body: result.suggested_reply });
    this.log("draft_created", { sink: this.name, lead_id: result.meta.lead_id });
  }
}
