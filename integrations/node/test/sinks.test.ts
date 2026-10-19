import { describe, expect, it, vi } from "vitest";

import { buildSinks } from "../src/config.js";
import { buildRawEmail, GmailDraftSink } from "../src/sinks/gmail.js";
import { GoogleAuth } from "../src/sinks/googleAuth.js";
import { GoogleSheetsCrmSink } from "../src/sinks/sheets.js";
import { SlackWebhookAlertSink, slackPayload } from "../src/sinks/slack.js";
import { CRM_COLUMNS, crmRow } from "../src/sinks/types.js";
import { HttpTriageClient } from "../src/triageClient.js";
import { RetryableError } from "../src/retry.js";
import { lead, result } from "./fixtures.js";

type Call = { url: string; init: RequestInit };

function fakeFetch(responder: (url: string) => Response = () => new Response("{}", { status: 200 })) {
  const calls: Call[] = [];
  const impl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    if (String(url).includes("oauth2.googleapis.com")) {
      return new Response(JSON.stringify({ access_token: "ya29.token", expires_in: 3600 }), { status: 200 });
    }
    return responder(String(url));
  }) as unknown as typeof fetch;
  return { impl, calls };
}

describe("Slack", () => {
  it("escapes lead text in every field Slack parses as mrkdwn", () => {
    const payload = slackPayload({ ...lead, name: "<!channel> Eve", company: null }, result("hot"));
    // plain_text blocks (the header) are never parsed for mentions, so only check mrkdwn.
    const mrkdwn = JSON.stringify([payload.text, payload.blocks.slice(1)]);
    expect(mrkdwn).not.toContain("<!channel>");
    expect(mrkdwn).toContain("&lt;!channel&gt;");
    expect(payload.blocks[0]).toMatchObject({ text: { type: "plain_text" } });
  });

  it("posts the payload to the incoming webhook URL", async () => {
    const { impl, calls } = fakeFetch(() => new Response("ok", { status: 200 }));
    await new SlackWebhookAlertSink("https://hooks.slack.com/services/T/B/X", impl).alert(lead, result("hot"));
    expect(calls[0]?.url).toBe("https://hooks.slack.com/services/T/B/X");
    expect(JSON.parse(String(calls[0]?.init.body)).text).toContain("Hot lead");
  });
});

describe("Google Sheets", () => {
  it("appends one RAW row with a bearer token", async () => {
    const { impl, calls } = fakeFetch();
    const auth = new GoogleAuth("id", "secret", "refresh", impl);
    await new GoogleSheetsCrmSink(auth, "sheet123", "Leads!A1", impl).appendLead(lead, result("warm"));
    const append = calls.find((c) => c.url.includes("sheets.googleapis.com"));
    expect(append?.url).toContain("/spreadsheets/sheet123/values/Leads!A1:append");
    expect(append?.url).toContain("valueInputOption=RAW");
    expect((append?.init.headers as Record<string, string>).Authorization).toBe("Bearer ya29.token");
    const row = JSON.parse(String(append?.init.body)).values[0];
    expect(row).toHaveLength(CRM_COLUMNS.length);
  });

  it("row columns line up with the header list", () => {
    const row = crmRow(lead, result("warm"));
    expect(row[CRM_COLUMNS.indexOf("email")]).toBe(lead.email);
    expect(row[CRM_COLUMNS.indexOf("routing")]).toBe("warm");
  });

  it("caches the access token between calls", async () => {
    const { impl, calls } = fakeFetch();
    const auth = new GoogleAuth("id", "secret", "refresh", impl);
    await auth.accessToken();
    await auth.accessToken();
    expect(calls.filter((c) => c.url.includes("oauth2")).length).toBe(1);
  });
});

describe("Gmail", () => {
  it("builds a decodable RFC 2822 message and strips header injection", () => {
    const raw = buildRawEmail("dana@example.com\r\nBcc: evil@example.com", "Hello", "Body text");
    const decoded = Buffer.from(raw, "base64url").toString("utf8");
    expect(decoded).toContain("To: dana@example.com Bcc: evil@example.com");
    expect(decoded).not.toMatch(/\r\nBcc:/);
    expect(decoded.endsWith("\r\n\r\nBody text")).toBe(true);
  });

  it("encodes non-ASCII subjects", () => {
    const decoded = Buffer.from(buildRawEmail("a@example.com", "Merci, René", "x"), "base64url").toString("utf8");
    expect(decoded).toContain("Subject: =?UTF-8?B?");
  });

  it("creates a draft through the Gmail API", async () => {
    const { impl, calls } = fakeFetch();
    const auth = new GoogleAuth("id", "secret", "refresh", impl);
    await new GmailDraftSink(auth, "Thanks", impl).createDraft(lead, result("hot"));
    const draft = calls.find((c) => c.url.includes("gmail.googleapis.com"));
    expect(draft?.url).toBe("https://gmail.googleapis.com/gmail/v1/users/me/drafts");
    const raw = JSON.parse(String(draft?.init.body)).message.raw;
    expect(Buffer.from(raw, "base64url").toString("utf8")).toContain(result("hot").suggested_reply);
  });
});

describe("HttpTriageClient", () => {
  it("sends the API key and maps 503 to a retryable error", async () => {
    const { impl, calls } = fakeFetch(() => new Response("busy", { status: 503 }));
    const client = new HttpTriageClient("http://core:8000/", "key-1", impl);
    await expect(client.triage(lead)).rejects.toBeInstanceOf(RetryableError);
    expect(calls[0]?.url).toBe("http://core:8000/triage");
    expect((calls[0]?.init.headers as Record<string, string>)["X-API-Key"]).toBe("key-1");
  });
});

describe("buildSinks", () => {
  it("falls back to console adapters without credentials", () => {
    const sinks = buildSinks({});
    expect([sinks.crm.name, sinks.alert.name, sinks.draft.name]).toEqual(["console-crm", "console-alert", "console-draft"]);
  });

  it("uses real adapters when credentials are present", () => {
    const sinks = buildSinks({
      GOOGLE_CLIENT_ID: "id",
      GOOGLE_CLIENT_SECRET: "secret",
      GOOGLE_REFRESH_TOKEN: "refresh",
      SHEETS_SPREADSHEET_ID: "sheet",
      SLACK_WEBHOOK_URL: "https://hooks.slack.com/services/x",
    });
    expect([sinks.crm.name, sinks.alert.name, sinks.draft.name]).toEqual(["google-sheets", "slack", "gmail"]);
  });
});
