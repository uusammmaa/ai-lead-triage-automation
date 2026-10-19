import { checkResponse, fetchWithTimeout } from "../retry.js";
import type { Lead, TriageResult } from "../types.js";
import type { GoogleAuth } from "./googleAuth.js";
import type { CrmSink } from "./types.js";
import { crmRow } from "./types.js";

/** Appends one row per lead via the Sheets API values.append endpoint. */
export class GoogleSheetsCrmSink implements CrmSink {
  readonly name = "google-sheets";

  constructor(
    private readonly auth: GoogleAuth,
    private readonly spreadsheetId: string,
    private readonly range = "Leads!A1",
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  async appendLead(lead: Lead, result: TriageResult): Promise<void> {
    const url =
      `https://sheets.googleapis.com/v4/spreadsheets/${encodeURIComponent(this.spreadsheetId)}` +
      `/values/${encodeURIComponent(this.range)}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS`;
    const res = await fetchWithTimeout(
      this.fetchImpl,
      url,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${await this.auth.accessToken()}`, "Content-Type": "application/json" },
        // RAW (not USER_ENTERED) so a lead typing "=IMPORTXML(...)" stays text, not a formula.
        body: JSON.stringify({ values: [crmRow(lead, result)] }),
      },
      15_000,
    );
    await checkResponse(res, "sheets append");
  }
}
