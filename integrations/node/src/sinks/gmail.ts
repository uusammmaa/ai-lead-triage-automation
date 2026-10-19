import { checkResponse, fetchWithTimeout } from "../retry.js";
import type { Lead, TriageResult } from "../types.js";
import type { GoogleAuth } from "./googleAuth.js";
import type { DraftSink } from "./types.js";

const noNewlines = (value: string) => value.replace(/[\r\n]+/g, " ").trim();

function encodeHeader(value: string): string {
  // RFC 2047 encoded-word, so names and subjects with accents survive.
  return /^[\x20-\x7e]*$/.test(value) ? value : `=?UTF-8?B?${Buffer.from(value, "utf8").toString("base64")}?=`;
}

/** Build the base64url RFC 2822 message the Gmail drafts API expects. */
export function buildRawEmail(to: string, subject: string, body: string): string {
  const message = [
    `To: ${noNewlines(to)}`,
    `Subject: ${encodeHeader(noNewlines(subject))}`,
    "MIME-Version: 1.0",
    'Content-Type: text/plain; charset="UTF-8"',
    "Content-Transfer-Encoding: 8bit",
    "",
    body,
  ].join("\r\n");
  return Buffer.from(message, "utf8").toString("base64url");
}

export class GmailDraftSink implements DraftSink {
  readonly name = "gmail";

  constructor(
    private readonly auth: GoogleAuth,
    private readonly subject = "Thanks for getting in touch",
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  async createDraft(lead: Lead, result: TriageResult): Promise<void> {
    const res = await fetchWithTimeout(
      this.fetchImpl,
      "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
      {
        method: "POST",
        headers: { Authorization: `Bearer ${await this.auth.accessToken()}`, "Content-Type": "application/json" },
        body: JSON.stringify({ message: { raw: buildRawEmail(lead.email, this.subject, result.suggested_reply) } }),
      },
      15_000,
    );
    await checkResponse(res, "gmail draft");
  }
}
