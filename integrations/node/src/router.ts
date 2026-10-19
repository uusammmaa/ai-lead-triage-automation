import type { Sinks } from "./sinks/types.js";
import type { Lead, Routing, TriageResult } from "./types.js";

export type Action = "crm" | "alert" | "draft";

/** Same routing table as the n8n, Zapier and Make builds. */
export const ROUTES: Record<Routing, Action[]> = {
  hot: ["crm", "alert", "draft"],
  warm: ["crm", "draft"],
  cold: ["crm"],
  discard: [],
};

export function actionsFor(routing: Routing): Action[] {
  return ROUTES[routing] ?? [];
}

export function runAction(action: Action, sinks: Sinks, lead: Lead, result: TriageResult): Promise<void> {
  switch (action) {
    case "crm":
      return sinks.crm.appendLead(lead, result);
    case "alert":
      return sinks.alert.alert(lead, result);
    case "draft":
      return sinks.draft.createDraft(lead, result);
  }
}
