import { ConsoleAlertSink, ConsoleCrmSink, ConsoleDraftSink } from "./sinks/console.js";
import { GmailDraftSink } from "./sinks/gmail.js";
import { GoogleAuth } from "./sinks/googleAuth.js";
import { GoogleSheetsCrmSink } from "./sinks/sheets.js";
import { SlackWebhookAlertSink } from "./sinks/slack.js";
import type { Sinks } from "./sinks/types.js";

export interface WorkerConfig {
  port: number;
  coreUrl: string;
  coreApiKey?: string;
  webhookSecret?: string;
  corsOrigins: string[];
}

type Env = Record<string, string | undefined>;

export function loadConfig(env: Env = process.env): WorkerConfig {
  return {
    port: Number(env.PORT ?? 3000),
    coreUrl: env.CORE_URL ?? "http://localhost:8000",
    coreApiKey: env.CORE_API_KEY || undefined,
    webhookSecret: env.WEBHOOK_SECRET || undefined,
    corsOrigins: (env.CORS_ORIGINS ?? "")
      .split(",")
      .map((o) => o.trim())
      .filter(Boolean),
  };
}

/** Real adapters when credentials exist, console adapters otherwise. */
export function buildSinks(env: Env = process.env, fetchImpl: typeof fetch = fetch): Sinks {
  const { GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN, SHEETS_SPREADSHEET_ID } = env;
  const google =
    GOOGLE_CLIENT_ID && GOOGLE_CLIENT_SECRET && GOOGLE_REFRESH_TOKEN
      ? new GoogleAuth(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN, fetchImpl)
      : undefined;
  return {
    crm:
      google && SHEETS_SPREADSHEET_ID
        ? new GoogleSheetsCrmSink(google, SHEETS_SPREADSHEET_ID, env.SHEETS_RANGE ?? "Leads!A1", fetchImpl)
        : new ConsoleCrmSink(),
    alert: env.SLACK_WEBHOOK_URL ? new SlackWebhookAlertSink(env.SLACK_WEBHOOK_URL, fetchImpl) : new ConsoleAlertSink(),
    draft: google
      ? new GmailDraftSink(google, env.DRAFT_SUBJECT ?? "Thanks for getting in touch", fetchImpl)
      : new ConsoleDraftSink(),
  };
}
