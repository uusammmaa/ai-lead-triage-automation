import { checkResponse, fetchWithTimeout } from "../retry.js";

/**
 * OAuth2 refresh-token flow for one Google account (the mailbox that owns the
 * drafts and the sheet). Scopes needed when generating the refresh token:
 *   https://www.googleapis.com/auth/spreadsheets
 *   https://www.googleapis.com/auth/gmail.compose
 */
export class GoogleAuth {
  private token: { value: string; expiresAt: number } | undefined;

  constructor(
    private readonly clientId: string,
    private readonly clientSecret: string,
    private readonly refreshToken: string,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  async accessToken(): Promise<string> {
    if (this.token && Date.now() < this.token.expiresAt - 60_000) return this.token.value;
    const res = await fetchWithTimeout(
      this.fetchImpl,
      "https://oauth2.googleapis.com/token",
      {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          client_id: this.clientId,
          client_secret: this.clientSecret,
          refresh_token: this.refreshToken,
          grant_type: "refresh_token",
        }),
      },
      10_000,
    );
    await checkResponse(res, "google token refresh");
    const body = (await res.json()) as { access_token: string; expires_in: number };
    this.token = { value: body.access_token, expiresAt: Date.now() + body.expires_in * 1000 };
    return body.access_token;
  }
}
