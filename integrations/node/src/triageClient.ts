import { checkResponse, fetchWithTimeout } from "./retry.js";
import type { Lead, TriageClient, TriageResult } from "./types.js";

export class HttpTriageClient implements TriageClient {
  constructor(
    private readonly baseUrl: string,
    private readonly apiKey: string | undefined,
    private readonly fetchImpl: typeof fetch = fetch,
    private readonly timeoutMs = 60_000,
  ) {}

  async triage(lead: Lead): Promise<TriageResult> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (this.apiKey) headers["X-API-Key"] = this.apiKey;
    const res = await fetchWithTimeout(
      this.fetchImpl,
      `${this.baseUrl.replace(/\/$/, "")}/triage`,
      { method: "POST", headers, body: JSON.stringify(lead) },
      this.timeoutMs,
    );
    await checkResponse(res, "core /triage");
    return (await res.json()) as TriageResult;
  }
}
