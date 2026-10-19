import request from "supertest";
import { describe, expect, it, vi } from "vitest";

import { createApp } from "../src/app.js";
import { RetryableError } from "../src/retry.js";
import { ConsoleAlertSink, ConsoleCrmSink, ConsoleDraftSink } from "../src/sinks/console.js";
import type { Routing, TriageClient } from "../src/types.js";
import { lead, noSleep, result } from "./fixtures.js";

const quiet = () => {};

function setup(routing: Routing = "hot", triageImpl?: TriageClient["triage"]) {
  const sinks = { crm: new ConsoleCrmSink(quiet), alert: new ConsoleAlertSink(quiet), draft: new ConsoleDraftSink(quiet) };
  const triage = { triage: vi.fn(triageImpl ?? (async () => result(routing))) };
  const app = createApp({ triage, sinks, retry: noSleep, log: quiet });
  return { app, sinks, triage };
}

describe("POST /webhook/lead", () => {
  it.each([
    ["hot", ["crm", "alert", "draft"]],
    ["warm", ["crm", "draft"]],
    ["cold", ["crm"]],
    ["discard", []],
  ] as const)("routes %s leads to %j", async (routing, expected) => {
    const { app, sinks } = setup(routing);
    const res = await request(app).post("/webhook/lead").send(lead);
    expect(res.status).toBe(200);
    expect(res.body.routing).toBe(routing);
    expect(res.body.actions.map((a: { action: string }) => a.action)).toEqual(expected);
    expect(sinks.crm.rows).toHaveLength(expected.includes("crm" as never) ? 1 : 0);
    expect(sinks.alert.alerts).toHaveLength(expected.includes("alert" as never) ? 1 : 0);
    expect(sinks.draft.drafts).toHaveLength(expected.includes("draft" as never) ? 1 : 0);
  });

  it("writes the suggested reply into the draft for the lead's address", async () => {
    const { app, sinks } = setup("warm");
    await request(app).post("/webhook/lead").send(lead);
    expect(sinks.draft.drafts[0]).toEqual({ to: lead.email, body: result("warm").suggested_reply });
  });

  it("rejects invalid payloads with 422", async () => {
    const { app, triage } = setup();
    const res = await request(app).post("/webhook/lead").send({ name: "x", email: "nope", message: "" });
    expect(res.status).toBe(422);
    expect(triage.triage).not.toHaveBeenCalled();
  });

  it("is idempotent: a redelivered lead is not triaged or routed twice", async () => {
    const { app, sinks, triage } = setup("hot");
    const first = await request(app).post("/webhook/lead").send(lead);
    const second = await request(app).post("/webhook/lead").send({ ...lead, message: `  ${lead.message.toUpperCase()} ` });
    expect(first.body.duplicate).toBe(false);
    expect(second.status).toBe(200);
    expect(second.body.duplicate).toBe(true);
    expect(second.body.lead_id).toBe(first.body.lead_id);
    expect(triage.triage).toHaveBeenCalledTimes(1);
    expect(sinks.crm.rows).toHaveLength(1);
    expect(sinks.alert.alerts).toHaveLength(1);
  });

  it("collapses concurrent deliveries of the same lead into one run", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const { app, triage, sinks } = setup("hot", async () => {
      await gate;
      return result("hot");
    });
    const a = request(app).post("/webhook/lead").send(lead).then((r) => r);
    const b = request(app).post("/webhook/lead").send(lead).then((r) => r);
    await new Promise((r) => setTimeout(r, 50));
    release();
    const [ra, rb] = await Promise.all([a, b]);
    expect([ra.status, rb.status]).toEqual([200, 200]);
    expect(triage.triage).toHaveBeenCalledTimes(1);
    expect(sinks.crm.rows).toHaveLength(1);
  });

  it("retries the core with backoff on 5xx", async () => {
    let calls = 0;
    const { app } = setup("hot", async () => {
      calls++;
      if (calls < 3) throw new RetryableError("core 503");
      return result("hot");
    });
    const res = await request(app).post("/webhook/lead").send(lead);
    expect(res.status).toBe(200);
    expect(calls).toBe(3);
  });

  it("returns 502 when the core stays down, so the sender can redeliver", async () => {
    const { app, sinks } = setup("hot", async () => {
      throw new RetryableError("core down");
    });
    const res = await request(app).post("/webhook/lead").send(lead);
    expect(res.status).toBe(502);
    expect(sinks.crm.rows).toHaveLength(0);
  });

  it("on partial failure returns 502 and a redelivery only re-runs the failed sink", async () => {
    const { app, sinks, triage } = setup("hot");
    const alert = vi.spyOn(sinks.alert, "alert").mockRejectedValueOnce(new Error("slack 400 invalid_payload"));
    const first = await request(app).post("/webhook/lead").send(lead);
    expect(first.status).toBe(502);
    expect(first.body.actions.find((a: { action: string }) => a.action === "alert").status).toBe("failed");

    const second = await request(app).post("/webhook/lead").send(lead);
    expect(second.status).toBe(200);
    const statuses = Object.fromEntries(second.body.actions.map((a: { action: string; status: string }) => [a.action, a.status]));
    expect(statuses).toEqual({ crm: "skipped", alert: "done", draft: "skipped" });
    expect(triage.triage).toHaveBeenCalledTimes(1);
    expect(sinks.crm.rows).toHaveLength(1);
    expect(alert).toHaveBeenCalledTimes(2);
  });

  it("enforces the shared webhook secret when configured", async () => {
    const sinks = { crm: new ConsoleCrmSink(quiet), alert: new ConsoleAlertSink(quiet), draft: new ConsoleDraftSink(quiet) };
    const app = createApp({ triage: { triage: async () => result() }, sinks, webhookSecret: "s3cret", log: quiet });
    expect((await request(app).post("/webhook/lead").send(lead)).status).toBe(401);
    expect((await request(app).post("/webhook/lead").set("X-Webhook-Secret", "wrong").send(lead)).status).toBe(401);
    expect((await request(app).post("/webhook/lead").set("X-Webhook-Secret", "s3cret").send(lead)).status).toBe(200);
  });

  it("reports sink names on /health", async () => {
    const { app } = setup();
    const res = await request(app).get("/health");
    expect(res.body).toEqual({ status: "ok", sinks: { crm: "console-crm", alert: "console-alert", draft: "console-draft" } });
  });
});
