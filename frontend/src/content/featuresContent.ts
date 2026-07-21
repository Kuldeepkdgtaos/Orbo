export const FEATURES_MD = `
### 🤖 Automated Meeting Facilitation
A bot (via **Recall.ai**) joins your Teams meeting on your behalf, posts a greeting in chat,
tracks the meeting lifecycle through a full state machine (\`idle → dispatched → joined →
greeting → completed\`), and leaves automatically when the meeting ends.

### 📝 Live Transcript Capture & Speaker Attribution
Every spoken line is captured and attributed to a participant — exact match on Teams display
name first, then fuzzy matching (85% threshold) for near-misses. Unattributed lines are kept
visible rather than silently dropped.

### 🧠 AI-Powered Summarization
**GPT-4o** generates a structured **yesterday / today / blockers** summary for each participant,
then an **executive rollup digest** for management — both role-aware (designation, department)
and manager-aware (the standup's manager gets named context in the digest).

### 📊 Automated Excel Reporting
A workbook is generated automatically with three sheets: **Rollup** (executive summary, wins,
blockers), **Per Person** (individual breakdowns), and **Full Transcript** (every attributed
line, timestamped).

### 📧 Email Delivery with Full Audit Trail
The digest is emailed to management via **Microsoft Graph**, with the Excel report attached.
If Graph isn't configured, delivery fails *gracefully* — the attempt, including the exact error,
is still recorded in the database rather than silently lost.

### 🔁 Recurring Standup Templates
Configure a team's roster and schedule once as a template, then spin up a new session with one
click whenever you need it — no need to re-enter participants every time.

### 📡 Live Status Streaming
The meeting detail page shows state transitions in real time via **Server-Sent Events**, with
automatic reconnection and replay of any missed events.

### 🔌 Hierarchical Agent Architecture — A2A + MCP
*New in this version.* Post-meeting processing is no longer a hardcoded pipeline — it's driven
by a real **agent-to-agent (A2A)** protocol call from the orchestrator to a dedicated
**Standup Manager Agent**, which in turn uses tools exposed over the **Model Context Protocol
(MCP)**. See the [Architecture](#architecture) section below for the full picture.

### ⚙️ Provider-Configurable Models
The model used for orchestration reasoning (\`LLM_PROVIDER\`) and the model used for email-intro
composition (\`SLM_PROVIDER\` / \`DELIVER_MODEL\`) are both swappable via environment variables —
no code changes needed to try a cheaper or local model.

### 🛡️ Resilient by Design
If the AI-driven orchestration path fails for any reason, a deterministic fallback calls the
same two skills directly, in order — a standup's summary and delivery are never silently
dropped just because an LLM misbehaved.
`

export const SETUP_MD = `
### Prerequisites
- Docker Desktop running
- A PostgreSQL instance you manage yourself (this app does **not** run Postgres for you)
- A [Recall.ai](https://recall.ai) API key (for the meeting bot)
- An Azure OpenAI resource with a \`gpt-4o\` deployment (for summarization)
- *(Optional)* Microsoft Graph app credentials, for real email delivery — leave blank to skip

### 1. Apply the database schema
One script, safe to re-run any time (every statement is idempotent):
\`\`\`bash
psql -U postgres -p 5433 -d standup -f db-setup.sql
\`\`\`

### 2. Configure environment variables
Copy \`.env.example\` to \`.env\` and fill in:
- \`DATABASE_URL\` — points at your Postgres (defaults to \`host.docker.internal:5433\`)
- \`RECALL_API_KEY\`, \`RECALL_WEBHOOK_SECRET\`, \`RECALL_REGION\`, \`RECALL_WEBHOOK_BASE_URL\`
- \`AZURE_OPENAI_ENDPOINT\`, \`AZURE_OPENAI_API_KEY\`, \`AZURE_OPENAI_DEPLOYMENT=gpt-4o\`
- \`MS_GRAPH_*\` — optional, leave blank to skip real email sending
- \`GATEWAY_API_KEY\` — the key this UI will use to talk to the backend

### 3. Build and start the containers
\`\`\`bash
docker compose build
docker compose up
\`\`\`
This starts four containers — \`standup-mcp\`, \`standup-agent\`, \`orchestrator\`, \`frontend\` —
each independently, in that dependency order.

### 4. Open the app and set your API key
Go to **http://localhost:3000 → Settings** and enter the same value as \`GATEWAY_API_KEY\`
in your \`.env\`.

### 5. Create a standup (or a template)
From the Dashboard, click **New Standup**, add participants (name, email, Teams display name,
optionally designation/department/manager flag), and a meeting URL.

### 6. Run a real meeting
Expose the orchestrator to Recall.ai's webhooks with ngrok, pointed at port **8000**:
\`\`\`bash
ngrok http --domain=<your-domain> 8000
\`\`\`
Then in the app: **Start Meeting** → admit the bot from the Teams lobby → turn on **Live
Captions** in Teams (required for transcript capture) → speak your updates → the bot leaves
automatically → summaries and the digest email are generated within moments.

### 7. Or test without a real meeting
Seed a few utterances directly into the database for an existing standup, then click
**Regenerate** on its detail page — this drives the exact same summarize → deliver pipeline
without needing a live Teams call.
`

export const ARCHITECTURE_MD = `
This version replaced a hardcoded, webhook-driven pipeline with a hierarchical
**agent-to-agent (A2A) + tool-calling (MCP)** architecture. The meeting runtime (talking to
Recall.ai, driving the state machine) stayed in one place; everything AI-driven now goes
through a real agent protocol instead of direct service-to-service HTTP calls.

\`\`\`
Frontend (React SPA, :3000)
      │  REST + SSE  (/api/*, Bearer JWT)
      ▼
┌────────────────────────────────────────────────┐
│ ORCHESTRATOR (:8000) — A2A CLIENT                │
│  • auth, CORS, SSE live status                    │
│  • standup + template CRUD (direct DB)            │
│  • Recall webhook ingress + meeting state machine │
│  • transcript ingest + speaker attribution        │
│  • Tier-1 ReAct agent whose tools are the         │
│    Standup Manager Agent's A2A skills             │
└───────────────┬────────────────────────────────┘
                │  A2A v0.3.0  (JSON-RPC 2.0, POST /a2a)
                ▼
┌────────────────────────────────────────────────┐
│ STANDUP MANAGER AGENT (:8020) — A2A SERVER        │
│  skill: summarize_standup  → GPT-4o               │
│  skill: deliver_report     → SLM + MCP tools      │
└───────────────┬────────────────────────────────┘
                │  MCP  (streamable-http, POST /mcp)
                ▼
┌────────────────────────────────────────────────┐
│ STANDUP-TOOLS MCP SERVER (:8010)                  │
│  tools: get_standup_context, save_summaries,      │
│         build_excel_report, send_email,           │
│         record_delivery                           │
└───────────────┬────────────────────────────────┘
                ▼
          PostgreSQL     (Recall.ai + MS Graph are external services)
\`\`\`

#### Orchestrator (A2A client)
Owns the meeting runtime end to end: receives Recall.ai webhooks, drives the state machine,
ingests and attributes the transcript. Once a meeting completes, it hands off to the agent —
either through a **Tier-1 ReAct agent** (an LLM reasoning about which A2A skill to call next)
or, if that path fails for any reason, a **deterministic fallback** that calls the same two
skills directly in order. Both paths check not just "did the call complete" but "did the skill
actually report success," since a failed A2A task comes back as data, not an exception.

#### Standup Manager Agent (A2A server)
Exposes exactly two skills over the A2A protocol:
- **\`summarize_standup\`** — always GPT-4o, a deliberate quality decision that isn't
  provider-configurable like the rest of the stack.
- **\`deliver_report\`** — builds the Excel report and sends the email. The configurable SLM's
  role here is narrow on purpose: it writes only a one-sentence email intro, constrained to the
  facts it's given, with a deterministic fallback sentence if it fails. The actual digest
  content is always the GPT-4o-generated rollup — the SLM never touches it.

Both skills call MCP tools **directly by name** rather than through their own ReAct loop —
they're fully deterministic pipelines (fetch → reason → save), so there's nothing to be gained
from letting an LLM choose the tool order, only risk.

#### standup-tools MCP server
The only place that touches the database for AI-driven operations, builds the Excel workbook,
and calls Microsoft Graph. No LLM reasoning happens here — it's pure, deterministic I/O, which
is exactly what makes it safe for an agent to call unsupervised. If Microsoft Graph isn't
configured, \`send_email\` returns a structured failure rather than raising, and that failure is
still recorded as an audit row.

#### Why hand-rolled A2A, not a third-party SDK?
The A2A protocol here (Task/Message/Part/Artifact, JSON-RPC 2.0 envelope, Agent Cards served at
\`/.well-known/agent-card.json\`) is implemented directly rather than via an external SDK,
mirroring the same approach taken by the reference architecture this design was modeled on.
`
