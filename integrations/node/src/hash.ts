import { createHash } from "node:crypto";

import type { Lead } from "./types.js";

/**
 * Idempotency key for a lead. Same normalisation as the Python core's
 * lead_id_for(), so the key matches meta.lead_id in the triage response.
 */
export function leadHash(lead: Pick<Lead, "email" | "message">): string {
  const email = lead.email.trim().toLowerCase();
  const message = lead.message.trim().split(/\s+/).join(" ").toLowerCase();
  return createHash("sha256").update(`${email}\n${message}`, "utf8").digest("hex").slice(0, 16);
}
