import { timingSafeEqual } from "node:crypto";

import express, { type Request, type Response } from "express";

import { leadHash } from "./hash.js";
import { type IdempotencyStore, InFlight, MemoryIdempotencyStore } from "./idempotency.js";
import { type RetryOptions, withRetry } from "./retry.js";
import { type Action, actionsFor, runAction } from "./router.js";
import { jsonLogger } from "./sinks/console.js";
import type { Sinks } from "./sinks/types.js";
import { type Lead, LeadSchema, type TriageClient } from "./types.js";

export interface AppDeps {
  triage: TriageClient;
  sinks: Sinks;
  store?: IdempotencyStore;
  retry?: RetryOptions;
  webhookSecret?: string;
  /** Browser origins allowed to post (for the demo form). Empty means no CORS headers. */
  corsOrigins?: string[];
  log?: (event: string, data: Record<string, unknown>) => void;
}

interface ActionOutcome {
  action: Action;
  sink: string;
  status: "done" | "skipped" | "failed";
  error?: string;
}

interface ProcessResult {
  status: number;
  body: Record<string, unknown>;
}

const DEFAULT_RETRY: RetryOptions = { retries: 3, baseDelayMs: 500, maxDelayMs: 8_000 };

function secretMatches(expected: string, given: string | undefined): boolean {
  if (!given) return false;
  const a = Buffer.from(expected);
  const b = Buffer.from(given);
  return a.length === b.length && timingSafeEqual(a, b);
}

export function createApp(deps: AppDeps) {
  const store = deps.store ?? new MemoryIdempotencyStore();
  const retry = deps.retry ?? DEFAULT_RETRY;
  const log = deps.log ?? jsonLogger;
  const inflight = new InFlight<ProcessResult>();
  const app = express();
  const corsOrigins = deps.corsOrigins ?? [];
  app.use((req, res, next) => {
    const origin = req.header("origin");
    if (origin && (corsOrigins.includes("*") || corsOrigins.includes(origin))) {
      res.setHeader("Access-Control-Allow-Origin", corsOrigins.includes("*") ? "*" : origin);
      res.setHeader("Vary", "Origin");
      res.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
      res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Webhook-Secret");
    }
    if (req.method === "OPTIONS") {
      res.sendStatus(204);
      return;
    }
    next();
  });
  app.use(express.json({ limit: "64kb" }));

  async function processLead(key: string, lead: Lead): Promise<ProcessResult> {
    const existing = await store.get(key);
    let result = existing?.result;
    if (!result) {
      result = await withRetry(() => deps.triage.triage(lead), {
        ...retry,
        onRetry: (attempt, delayMs, error) =>
          log("core_retry", { lead_id: key, attempt, delay_ms: delayMs, error: String(error) }),
      });
    }
    const completed = new Set(existing?.completed ?? []);
    const sinkName = { crm: deps.sinks.crm.name, alert: deps.sinks.alert.name, draft: deps.sinks.draft.name };

    const outcomes: ActionOutcome[] = await Promise.all(
      actionsFor(result.routing).map(async (action): Promise<ActionOutcome> => {
        if (completed.has(action)) return { action, sink: sinkName[action], status: "skipped" };
        try {
          await withRetry(() => runAction(action, deps.sinks, lead, result), retry);
          completed.add(action);
          return { action, sink: sinkName[action], status: "done" };
        } catch (error) {
          log("sink_failed", { lead_id: key, action, error: String(error) });
          return { action, sink: sinkName[action], status: "failed", error: String(error).slice(0, 300) };
        }
      }),
    );
    await store.set(key, { result, completed: [...completed], updatedAt: Date.now() });

    const failed = outcomes.some((o) => o.status === "failed");
    log("lead_processed", {
      lead_id: key,
      routing: result.routing,
      category: result.category,
      score: result.lead_score,
      mode: result.meta.mode,
      failed,
    });
    return {
      // 502 tells the webhook sender to redeliver; completed sinks are skipped next time.
      status: failed ? 502 : 200,
      body: {
        lead_id: key,
        duplicate: Boolean(existing) && outcomes.every((o) => o.status === "skipped"),
        category: result.category,
        lead_score: result.lead_score,
        routing: result.routing,
        summary: result.summary,
        triage_mode: result.meta.mode,
        actions: outcomes,
      },
    };
  }

  app.get("/health", (_req: Request, res: Response) => {
    res.json({
      status: "ok",
      sinks: { crm: deps.sinks.crm.name, alert: deps.sinks.alert.name, draft: deps.sinks.draft.name },
    });
  });

  app.post("/webhook/lead", async (req: Request, res: Response) => {
    if (deps.webhookSecret && !secretMatches(deps.webhookSecret, req.header("x-webhook-secret"))) {
      res.status(401).json({ error: "invalid webhook secret" });
      return;
    }
    const parsed = LeadSchema.safeParse(req.body);
    if (!parsed.success) {
      res.status(422).json({ error: "invalid lead", issues: parsed.error.issues });
      return;
    }
    const lead = parsed.data;
    const key = leadHash(lead);
    try {
      const { promise, joined } = inflight.run(key, () => processLead(key, lead));
      const outcome = await promise;
      res.status(outcome.status).json(joined ? { ...outcome.body, duplicate: true } : outcome.body);
    } catch (error) {
      log("lead_failed", { lead_id: key, error: String(error) });
      res.status(502).json({ lead_id: key, error: "triage failed, safe to retry" });
    }
  });

  return app;
}
