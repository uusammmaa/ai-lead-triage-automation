import { createApp } from "./app.js";
import { buildSinks, loadConfig } from "./config.js";
import { jsonLogger } from "./sinks/console.js";
import { HttpTriageClient } from "./triageClient.js";

const config = loadConfig();
const sinks = buildSinks();
const app = createApp({
  triage: new HttpTriageClient(config.coreUrl, config.coreApiKey),
  sinks,
  webhookSecret: config.webhookSecret,
});

app.listen(config.port, () => {
  jsonLogger("worker_started", {
    port: config.port,
    core_url: config.coreUrl,
    sinks: { crm: sinks.crm.name, alert: sinks.alert.name, draft: sinks.draft.name },
  });
});
