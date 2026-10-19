import type { Lead, TriageResult } from "../types.js";

/** Where every non-discarded lead is logged (Google Sheets, HubSpot, Pipedrive...). */
export interface CrmSink {
  readonly name: string;
  appendLead(lead: Lead, result: TriageResult): Promise<void>;
}

/** Real-time alert for hot leads (Slack, Teams, WhatsApp...). */
export interface AlertSink {
  readonly name: string;
  alert(lead: Lead, result: TriageResult): Promise<void>;
}

/** Saves the suggested reply as a draft for a human to review and send. */
export interface DraftSink {
  readonly name: string;
  createDraft(lead: Lead, result: TriageResult): Promise<void>;
}

export interface Sinks {
  crm: CrmSink;
  alert: AlertSink;
  draft: DraftSink;
}

export const CRM_COLUMNS = [
  "received_at",
  "lead_id",
  "name",
  "email",
  "company",
  "source",
  "category",
  "lead_score",
  "routing",
  "urgency",
  "budget_signal",
  "summary",
  "email_type",
  "domain",
  "score_reasons",
  "suggested_reply",
  "triage_mode",
] as const;

export function crmRow(lead: Lead, result: TriageResult, now = new Date()): (string | number)[] {
  return [
    now.toISOString(),
    result.meta.lead_id,
    lead.name,
    lead.email,
    lead.company ?? result.enrichment.company_guess ?? "",
    lead.source,
    result.category,
    result.lead_score,
    result.routing,
    result.urgency,
    result.budget_signal,
    result.summary,
    result.enrichment.email_type,
    result.enrichment.domain,
    result.score_reasons.join("; "),
    result.suggested_reply,
    result.meta.mode,
  ];
}
