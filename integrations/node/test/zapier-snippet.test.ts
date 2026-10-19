import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// The Code by Zapier snippet uses a top-level `return` on `inputData`, exactly
// as Zapier runs it, so load it the same way Zapier does: as a function body.
const source = readFileSync(fileURLToPath(new URL("../../zapier/code-by-zapier.js", import.meta.url)), "utf8");
const runSnippet = new Function("inputData", source) as (input: Record<string, string>) => Record<string, unknown>;

const base = {
  lead_score: "88",
  category: "sales_inquiry",
  urgency: "high",
  budget_signal: "explicit",
  summary: "Freight company wants AI lead qualification.",
  suggested_reply: "Hi Dana, thanks for reaching out.",
  score_reasons: "Explicit budget,Business email",
  email_type: "business",
  domain: "brightpath-logistics.example.com",
  lead_id: "abc",
  mode: "live",
  lead_name: "Dana Whitfield",
  lead_email: "dana@brightpath-logistics.example.com",
  lead_company: "Brightpath Logistics",
  lead_source: "webform",
};

describe("Code by Zapier snippet", () => {
  it.each([
    ["hot", true, true, true],
    ["warm", true, false, true],
    ["cold", true, false, false],
    ["discard", false, false, false],
  ])("maps %s to the right path flags", (routing, log, hot, draft) => {
    const out = runSnippet({ ...base, routing });
    expect(out).toMatchObject({ should_log: log, is_hot: hot, needs_draft: draft, routing });
  });

  it("parses the score and builds the draft fields", () => {
    const out = runSnippet({ ...base, routing: "hot" });
    expect(out.lead_score).toBe(88);
    expect(out.draft_body).toBe(base.suggested_reply);
    expect(out.slack_text).toContain("Dana Whitfield (Brightpath Logistics)");
  });

  it("escapes Slack control characters from lead text", () => {
    const out = runSnippet({ ...base, routing: "hot", lead_name: "<!channel> Eve" });
    expect(out.slack_text).not.toContain("<!channel>");
  });

  it("treats an unknown routing value as cold so nothing is lost and nobody is paged", () => {
    expect(runSnippet({ ...base, routing: "" })).toMatchObject({ routing: "cold", should_log: true, is_hot: false });
  });
});
