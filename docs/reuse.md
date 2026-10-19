# Ready-to-use copy

Copy derived from this project. Everything here describes what the repository actually contains; numbers come from the README and eval results. Swap in live eval numbers once you have run `python evals/run_evals.py --mode live`.

Repository link to use: `https://github.com/uusammmaa/ai-lead-triage-automation`

---

## 1. Upwork portfolio item

**Title**

AI Lead Triage Agent: Claude scores and routes leads to CRM, Slack and Gmail (n8n, Zapier, Make or Node)

**Description**

Inbound leads were being answered in arrival order, so high-value enquiries waited behind spam, job applications and support tickets. I built an AI lead triage system that reads every lead in seconds and routes it automatically.

A Claude agent classifies each lead (sales, support, partnership, job seeker, spam), scores it 0 to 100 with plain-English reasons based on the client's own scoring rules, enriches it (business or free email, company, budget signal, urgency) and writes a short first reply. Hot leads trigger a Slack alert and a Gmail draft, warm leads get a draft, everything worth keeping is logged to the CRM sheet, and spam is discarded.

The AI lives in one Python API, with four delivery options so the client can use the tool they already pay for: an importable n8n workflow, a Zapier build, a Make scenario, or a TypeScript worker with no platform fees.

Built for production: validated structured output with automatic retry and a rules-based fallback, prompt-injection protection, API key auth and rate limiting, cost tracking per lead (about $10 per 1,000 leads on Claude Sonnet), Docker, 128 automated tests and an evaluation suite in CI.

**Skills tags**

AI Agent Development, Claude API, Anthropic, n8n, Zapier, Make.com, Python, FastAPI, TypeScript, Node.js, Lead Generation Automation, CRM Automation, Google Sheets API, Gmail API, Slack API, Workflow Automation, Prompt Engineering, LLM Integration

---

## 2. Proposal paragraphs

### For lead handling, lead qualification or CRM automation jobs

I recently built an AI lead triage system that does what you describe: every inbound lead is classified, scored 0 to 100 with clear reasons, enriched (business email, company, budget, urgency) and routed automatically, with hot leads alerted in Slack, a reply drafted in Gmail for your team to approve, and everything logged to your CRM. Spam and job applications never reach your sales team. The scoring rules live in a simple file, so you decide what a hot lead means for your business, and I can connect it to HubSpot, Pipedrive or Google Sheets. You can see the working project here: https://github.com/uusammmaa/ai-lead-triage-automation

### For AI agent or LLM integration jobs

I build AI agents that are safe to put in front of real data. My lead triage project is a good example: a Claude agent that uses tools (scoring rules lookup, email enrichment, optional website check) and returns strictly validated JSON, with an automatic correction retry, a rules-based fallback so nothing is dropped when the API is down, prompt-injection defences, and token cost tracked on every call. It ships with an evaluation suite and 128 tests running in CI, which is how I make sure an agent keeps working after the prompt or model changes. Code: https://github.com/uusammmaa/ai-lead-triage-automation

### For n8n, Zapier or Make jobs

I work across n8n, Zapier and Make, and I can tell you honestly which fits your volume and budget. In my lead triage project the same AI core is delivered four ways: an importable n8n workflow (tested on n8n 2.43.8), a step-by-step Zapier build with Paths and a Code step, a Make scenario with a router, and a plain TypeScript worker for teams that want to avoid platform fees. Each version routes hot leads to Slack, drafts replies in Gmail and logs to Google Sheets, with retries and duplicate protection. I would start by mapping your current tools, then build in whichever platform you already use. Examples: https://github.com/uusammmaa/ai-lead-triage-automation

---

## 3. LinkedIn personal post angle (engineering depth)

**Angle:** "Let the model judge, let code decide." What it takes to make an LLM agent safe enough to route real leads.

**Draft**

I built an AI agent that triages inbound leads, and the most important design decision was what the model is *not* allowed to decide.

Claude reads the lead, calls a few tools (the client's scoring rules, an email domain check) and returns a category, a 0 to 100 score with reasons, and a drafted reply. That is the judgement part, and models are good at it.

But three things stay in code:

1. Facts. Whether an email is a business, free or disposable address comes from a lookup, not the model.
2. Policy. Routing (hot, warm, cold, discard) comes from thresholds in a YAML file the client edits.
3. Safety. Lead text is wrapped as data, and any lead containing instructions aimed at the AI is capped below "hot", so a prompt injection can at worst earn a human review.

Around that: structured output validated with Pydantic, one correction retry, then a deterministic rules engine so a lead is never dropped. Token usage and cost are logged per call. An eval set of 30 labelled leads, including two injection attempts, runs in CI next to 128 tests.

The same core then plugs into n8n, Zapier, Make or a TypeScript worker, because the intelligence should not depend on the automation tool.

Code is open: https://github.com/uusammmaa/ai-lead-triage-automation

What do you keep out of the model's hands in your agents?

---

## 4. Jezerox company page post angle (business outcome)

**Angle:** speed to lead. Stop answering leads in arrival order.

**Draft**

Your best lead of the week might be sitting behind an SEO pitch, two job applications and a support ticket.

Most teams answer enquiries in the order they arrive. We built an AI lead triage system that answers them in order of value instead:

- Every lead is read, categorised and scored in seconds, with the reasons spelled out.
- Hot leads alert your sales channel instantly, with a reply already drafted for approval.
- Everything worth keeping lands in your CRM. Spam never reaches a person.

It works with the tools you already use, whether that is n8n, Zapier, Make or a custom integration, and with Google Sheets, HubSpot or Pipedrive. You decide what a hot lead looks like; the system follows your rules.

Running cost is around a cent per lead for the AI.

If leads are going cold before your team gets to them, let's talk.

---

## 5. CV bullet points (AI engineer roles)

- Built a production-style AI lead triage agent on the Claude API (Python, FastAPI): tool-calling loop with schema-validated structured output, automatic correction retry and a deterministic fallback engine, prompt-injection defences, per-call token and cost metering, and an evaluation harness running in GitHub Actions alongside 128 tests.
- Designed the agent as a single API delivered through four integration paths (n8n, Zapier, Make and a TypeScript worker with idempotent, retrying Google Sheets, Slack and Gmail adapters), letting clients adopt it on their existing automation stack without changing the AI logic.
