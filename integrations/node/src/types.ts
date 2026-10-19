import { z } from "zod";

export const LeadSchema = z.object({
  name: z.string().trim().min(1).max(200),
  email: z.string().trim().email().max(254),
  company: z
    .string()
    .trim()
    .max(200)
    .nullish()
    .transform((v) => (v ? v : null)),
  message: z.string().trim().min(1).max(5000),
  source: z.string().trim().min(1).max(50).default("webform"),
});

export type Lead = z.infer<typeof LeadSchema>;

export type Routing = "hot" | "warm" | "cold" | "discard";

/** Response contract of the Python core's POST /triage. */
export interface TriageResult {
  category: "sales_inquiry" | "support" | "partnership" | "job_seeker" | "spam" | "other";
  lead_score: number;
  score_reasons: string[];
  urgency: "low" | "medium" | "high";
  budget_signal: "none" | "mentioned" | "explicit";
  summary: string;
  enrichment: { email_type: "business" | "free" | "disposable"; domain: string; company_guess: string | null };
  suggested_reply: string;
  routing: Routing;
  meta: {
    lead_id: string;
    mode: "live" | "mock" | "fallback";
    model: string | null;
    latency_ms: number;
    cost_usd: number;
    injection_detected: boolean;
  };
}

export interface TriageClient {
  triage(lead: Lead): Promise<TriageResult>;
}
