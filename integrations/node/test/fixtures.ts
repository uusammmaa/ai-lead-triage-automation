import type { Lead, Routing, TriageResult } from "../src/types.js";

export const lead: Lead = {
  name: "Dana Whitfield",
  email: "dana.whitfield@brightpath-logistics.example.com",
  company: "Brightpath Logistics",
  message: "We have a budget of $15,000 and want lead triage within two weeks.",
  source: "webform",
};

export function result(routing: Routing = "hot", overrides: Partial<TriageResult> = {}): TriageResult {
  return {
    category: routing === "discard" ? "spam" : "sales_inquiry",
    lead_score: { hot: 90, warm: 60, cold: 30, discard: 0 }[routing],
    score_reasons: ["Explicit budget", "Business email"],
    urgency: "high",
    budget_signal: "explicit",
    summary: "Freight company wants AI lead qualification.",
    enrichment: { email_type: "business", domain: "brightpath-logistics.example.com", company_guess: "Brightpath Logistics" },
    suggested_reply: "Hi Dana, thanks for reaching out. Could we book a call this week?",
    routing,
    meta: { lead_id: "abc", mode: "mock", model: null, latency_ms: 1, cost_usd: 0, injection_detected: false },
    ...overrides,
  };
}

export const noSleep = { retries: 3, baseDelayMs: 1, maxDelayMs: 1, sleep: async () => {} };
