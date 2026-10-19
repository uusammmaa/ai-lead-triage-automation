import { describe, expect, it } from "vitest";

import { leadHash } from "../src/hash.js";

describe("leadHash", () => {
  it("matches the Python core's lead_id_for() for the same lead", () => {
    // Vector computed with core/app/triage.py lead_id_for().
    const hash = leadHash({ email: " Dana@Brightpath-Logistics.example.com ", message: "We need   lead triage,\n budget $15k." });
    expect(hash).toBe("0121c8c396be8022");
  });

  it("ignores case and whitespace differences", () => {
    const a = leadHash({ email: "a@acme.example.com", message: "Need  a quote\nplease" });
    const b = leadHash({ email: "A@ACME.example.com", message: "need a quote please " });
    expect(a).toBe(b);
  });

  it("differs when the message differs", () => {
    expect(leadHash({ email: "a@x.example.com", message: "one" })).not.toBe(
      leadHash({ email: "a@x.example.com", message: "two" }),
    );
  });
});
