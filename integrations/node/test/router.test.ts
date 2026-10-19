import { describe, expect, it } from "vitest";

import { actionsFor } from "../src/router.js";

describe("routing table", () => {
  it("matches the n8n, Zapier and Make builds", () => {
    expect(actionsFor("hot")).toEqual(["crm", "alert", "draft"]);
    expect(actionsFor("warm")).toEqual(["crm", "draft"]);
    expect(actionsFor("cold")).toEqual(["crm"]);
    expect(actionsFor("discard")).toEqual([]);
  });
});
