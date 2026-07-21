# Implementation Plan — Migrate AI Standup Manager to A2A + MCP

> **For the implementing model (Sonnet):** Execute phases **in order**. Each phase is
> self-contained and ends with a **Verify** step — do not proceed until it passes. Reuse
> existing code wherever named; only write new *connective* code. Reference-pattern files live
> under `REF = C:\Users\Dell\Documents\TAOS\AskNIKICodeV04\AskDIA_PGVectorAdvanced`. The existing
> app lives under `APP = c:\Users\Dell\Documents\MyPOC\AgentAsManager\ai-standup-manager`.
> **Do not invent an A2A SDK** — A2A is hand-rolled JSON-RPC 2.0 over `httpx` (copy from REF).
> Windows + PowerShell; Docker Desktop. Keep the existing PostgreSQL schema unchanged.

---

## Context

The current app is a 6-service webhook-driven `if/elif` pipeline with no real agent, no tool
protocol, and plain `chat.completions` calls. We are migrating to the hierarchical pattern from
REF: an **LLM orchestrator (A2A client)** delegates to a **Standup Manager Agent (A2A server)**,
which uses **tools over MCP**. Functionality is preserved; architecture changes.

**This iteration:** one orchestrator + one agent + one MCP server. Meeting runtime stays in the
orchestrator; **summarize** & **deliver** become agent skills; GPT-4o for summaries, SLM elsewhere;
local `docker-compose` now (Azure Container Apps pipeline is a follow-up).

## Target layout (new)

```
ai-standup-manager/
├─ docker-compose.yml                 # REWRITE: postgres, mcp, agent, orchestrator, frontend
├─ .env / .env.example                # EXTEND with A2A/MCP/model vars
├─ Dockerfile.orchestrator            # NEW
├─ Dockerfile.agent                   # NEW
├─ Dockerfile.mcp                     # NEW
├─ Dockerfile.migrate                 # keep
├─ migrations/                        # keep unchanged
├─ frontend/                          # keep; only API base → orchestrator
├─ shared/  (from services/shared/shared) # reused by all 3 py components
├─ a2a/                               # NEW protocol layer
│   ├─ __init__.py
│   ├─ a2a_models.py                  # copy REF slm_agents/a2a_models.py (verbatim)
│   ├─ a2a_client.py                  # copy REF services/a2a_client.py (adjust import path)
│   └─ agent_cards.py                 # NEW: STANDUP_AGENT_CARD (2 skills)
├─ orchestrator/
│   ├─ __init__.py
│   ├─ main.py                        # FastAPI: auth, CORS, SSE, routes, webhooks, meeting runtime
│   ├─ recall_client.py              # move from meeting_orchestrator/app
│   ├─ attribution.py                # move from transcription_service/app
│   ├─ webhooks.py                   # move (sig verify + dedup)
│   ├─ state_machine.py             # move
│   ├─ a2a_registry.py              # copy REF orchestrator/a2a_registry.py (adjust imports)
│   ├─ llm_service.py               # NEW: GPT-4o/Claude/Ollama for orchestrator
│   ├─ react_agent.py               # NEW: Tier-1 ReAct that calls A2A skills
│   └─ routes/ (standups.py, templates.py, transcript.py)  # move + transcript reads
├─ agent/
│   ├─ __init__.py
│   ├─ server.py                     # copy REF slm_agents/sql_agent_server.py structure
│   ├─ slm_llm_service.py            # copy REF services/slm_llm_service.py
│   ├─ mcp_config.py                 # MultiServerMCPClient config → standup-mcp
│   ├─ skills/summarize.py           # GPT-4o per-person + rollup
│   ├─ skills/deliver.py             # SLM compose + MCP tool calls
│   └─ prompts/ (per_person.py, rollup.py, chat.py)  # move from summarization/meeting
└─ mcp_server/
    ├─ __init__.py
    ├─ standup_tools_server.py       # FastMCP; 5 tools
    ├─ excel_builder.py              # move from delivery_service/app
    └─ graph_client.py              # move from delivery_service/app
```

---

## Phase 0 — Scaffolding

1. Create dirs: `a2a/`, `orchestrator/`, `orchestrator/routes/`, `agent/`, `agent/skills/`,
   `agent/prompts/`, `mcp_server/` (each with `__init__.py`).
2. Copy `services/shared/shared/` → `ai-standup-manager/shared/` (top-level, importable as `shared`).
   Keep `services/shared/pyproject.toml` semantics; all 3 components install `shared` as a local package.
3. **Verify:** `python -c "import ast"` sanity only; dirs exist. No behavior yet.

## Phase 1 — Extend shared config

File: `shared/shared/config.py` (extend the `Settings` class; keep existing fields).
Add (defaults chosen so it runs locally via compose):
```python
# LLM orchestrator (A2A client)
llm_provider: str = "azure_openai"          # azure_openai | anthropic | ollama
anthropic_api_key: str = ""
ollama_base_url: str = "http://host.docker.internal:11434"

# SLM (agent side)
slm_provider: str = "azure_openai"          # azure_openai | groq | ollama
groq_api_key: str = ""
summarize_model: str = "gpt-4o"             # Azure deployment for summarize skill
deliver_model: str = "gpt-4o"              # SLM for deliver skill (swap to gemma/etc later)

# A2A
standup_agent_enabled: bool = True
standup_agent_host: str = "standup-agent"
standup_agent_port: int = 8020
a2a_scheme: str = "http"

# MCP
mcp_scheme: str = "http"
mcp_host: str = "standup-mcp"
mcp_port: int = 8010
```
**Verify:** `python -c "from shared.config import settings; print(settings.mcp_host)"`.

## Phase 2 — A2A protocol layer (`a2a/`)

1. `a2a/a2a_models.py` — **copy `REF/slm_agents/a2a_models.py` verbatim** (Task, TaskState,
   TextPart/DataPart/FilePart, Message, Artifact, TaskStatus, JSONRPCRequest/Response/Error,
   MessageSendParams, AgentCard/AgentSkill/AgentCapabilities/AgentInterface/AgentProvider).
2. `a2a/a2a_client.py` — **copy `REF/services/a2a_client.py`**; change the import from
   `from slm_agents.a2a_models import ...` → `from a2a.a2a_models import ...`. Keep
   `get_agent_card`, `send_message`, `send_task`, `get_task`, `health_check`.
3. `a2a/agent_cards.py` — define `STANDUP_AGENT_CARD = AgentCard(name="standup-manager-agent", …)`
   with two skills (mirror the shape of `REF/slm_agents/agent_cards.py`):
   - **`summarize_standup`** — `inputSchema`: `{ required:["standup_id"], properties:{ standup_id:string } }`.
   - **`deliver_report`** — `inputSchema`: `{ required:["standup_id"], properties:{ standup_id:string,
     force_resend:{type:boolean,default:false} } }`.
   `supportedInterfaces=[AgentInterface(url="")]` (filled at runtime), `capabilities.streaming=False`.
**Verify:** `python -c "from a2a.agent_cards import STANDUP_AGENT_CARD; print([s.id for s in STANDUP_AGENT_CARD.skills])"`
→ `['summarize_standup', 'deliver_report']`.

## Phase 3 — MCP server (`mcp_server/standup_tools_server.py`)

Copy the FastMCP skeleton from `REF/mcp_servers/comms_server.py` (header, `sys.path.insert`,
`mcp = FastMCP("standup-tools", host="0.0.0.0", port=settings.mcp_port, stateless_http=True)`,
`mcp.run(transport="streamable-http")`). Move `delivery_service/app/excel_builder.py` and
`graph_client.py` into `mcp_server/`. Implement 5 `@mcp.tool()` functions (type-hinted + docstring —
FastMCP infers the schema). Use an async SQLAlchemy session from `shared.db` for DB tools:

- `get_standup_context(standup_id: str) -> dict` — return `{team_name, date, participants:[{id,name,
  designation,department,is_manager}], per_person:[{participant_id,name,transcript}], manager:{…}}`.
  Reuse the utterance-gathering + roster logic from
  `summarization_service/app/routes/summaries.py` (the `or_` attributed/unattributed query).
- `save_summaries(standup_id, per_person: list, rollup: dict) -> dict` — upsert `ParticipantSummary`
  rows + `StandupSummary` (copy the upsert logic from `summaries.py:97-164`). Set `model`,
  `prompt_version`.
- `build_excel_report(standup_id: str) -> dict` — load summaries+utterances (like
  `delivery_service/app/routes/delivery.py`), call `build_excel(...)`, return
  `{filename, attachment_b64, content_type}`.
- `send_email(recipient_emails: list, subject: str, html_body: str, attachment_b64: str = "",
  attachment_filename: str = "report.xlsx") -> dict` — reuse `graph_client.send_email` (decode b64).
  Return `{success, message_id, error}`.
- `record_delivery(standup_id, recipients: list, subject, body_preview, message_id, status, error="")
  -> dict` — insert `EmailDelivery`.

**Verify (standalone):** run `python mcp_server/standup_tools_server.py`; from a scratch script use
`langchain_mcp_adapters.client.MultiServerMCPClient({"standup-tools":{"url":"http://localhost:8010/mcp",
"transport":"streamable_http"}})` → `await get_tools()` lists all 5 tool names.

## Phase 4 — Standup Manager Agent (`agent/`)

1. `agent/slm_llm_service.py` — **copy `REF/services/slm_llm_service.py`** (`create_slm_model` for
   azure_openai/groq/ollama). Remove the module-level `mcp_chat_model` singleton (not needed here).
   Read from `shared.config.settings` (map `AZURE_*` env names already present in existing config).
2. `agent/mcp_config.py` — `STANDUP_MCP_CONFIG = {"standup-tools": {"url":
   f"{settings.mcp_scheme}://{settings.mcp_host}:{settings.mcp_port}/mcp", "transport":
   "streamable_http"}}`.
3. `agent/prompts/` — move `summarization_service/app/prompts/per_person.py` + `rollup.py`.
4. `agent/skills/summarize.py` — implement `async def run_summarize(standup_id) -> dict`:
   - `mcp = MultiServerMCPClient(STANDUP_MCP_CONFIG); tools = await mcp.get_tools()`.
   - Call `get_standup_context` tool → context. Build GPT-4o model via existing
     `summarization_service/app/azure_openai_client.py` logic (reuse `summarize_person`/
     `summarize_rollup`) OR via `create_slm_model(settings.summarize_model,…)`. **Use GPT-4o.**
   - Produce `per_person[]` + `rollup{rollup_markdown,key_wins,key_blockers}` (reuse the key_wins/
     key_blockers parsing at `summaries.py:145-146`).
   - Call `save_summaries` tool. Return `{status:"completed", participants: N, rollup_present: true}`.
5. `agent/skills/deliver.py` — `async def run_deliver(standup_id, force_resend=False) -> dict`:
   - Use SLM (`create_slm_model(settings.deliver_model,…)`) to compose subject + HTML body from the
     rollup (fetch via `get_standup_context`/summaries). Keep it simple; the SLM only writes copy.
   - Call `build_excel_report` → attachment; `send_email` → message id; `record_delivery`.
   - Return `{status, message_id}`.
6. `agent/server.py` — **copy the structure of `REF/slm_agents/sql_agent_server.py`**:
   - `app = FastAPI(...)`, in-memory `_task_store`.
   - `GET /.well-known/agent-card.json` (dump `STANDUP_AGENT_CARD`, inject
     `supportedInterfaces[0].url = http://{host}:{port}/a2a`), `GET /.well-known/agent.json` redirect,
     `GET /health`.
   - `POST /a2a` JSON-RPC dispatcher → `message/send`, `tasks/get`, `tasks/cancel` (copy
     `_handle_tasks_get`/`_handle_tasks_cancel` verbatim).
   - `_extract_skill_data(message)` (copy). `_handle_message_send`: pop `_skill`; route
     `summarize_standup → run_summarize`, `deliver_report → run_deliver`; wrap result in an
     `Artifact(name=..., parts=[DataPart(data=result)])`; Task lifecycle SUBMITTED→WORKING→COMPLETED/FAILED;
     store in `_task_store`; return `JSONRPCResponse`.
   - `if __name__=="__main__": uvicorn.run(app, host="0.0.0.0", port=settings.standup_agent_port)`.
**Verify:** run agent; `curl http://localhost:8020/.well-known/agent-card.json`; POST a
`message/send` with `{"_skill":"summarize_standup","standup_id":"<seeded id>"}` (seed utterances via
SQL per the `project_ai_standup_manager.md` memory) → Task COMPLETED, summaries in DB.

## Phase 5 — Orchestrator (`orchestrator/`)

1. Move into `orchestrator/`: `recall_client.py`, `webhooks.py`, `state_machine.py` (from
   meeting_orchestrator), `attribution.py` (from transcription_service).
2. `orchestrator/a2a_registry.py` — **copy `REF/orchestrator/a2a_registry.py`**; adjust:
   `_setup_from_settings` registers only the standup agent when `settings.standup_agent_enabled`
   (url `f"{a2a_scheme}://{standup_agent_host}:{standup_agent_port}"`); imports `from a2a.a2a_client
   import A2AClient`. Keep `_build_args_schema` + `_skill_to_tool` verbatim.
3. `orchestrator/llm_service.py` — `get_orchestrator_model()` returning AzureChatOpenAI (default),
   ChatAnthropic, or ChatOllama by `settings.llm_provider` (mirror `REF/services/llm_service.py:29-58`).
4. `orchestrator/react_agent.py` — `async def process_standup(standup_id)`:
   `tools = await agent_registry.get_tools()`; `agent = create_react_agent(get_orchestrator_model(),
   tools)`; invoke with a prompt: *"Standup {id} has ended. Call summarize_standup, then
   deliver_report."* Include a **deterministic fallback**: if the ReAct path errors, call the two
   A2A skills in sequence directly via `agent_registry` clients.
5. `orchestrator/routes/` — move `standups.py`, `templates.py`; add `transcript.py` with the
   transcript-read endpoints from `transcription_service/app/routes/utterances.py`
   (`GET /standups/{id}/utterances`, per-participant). Add utterance **ingest** as an internal
   function (not a separate service) reusing `attribution.attribute_speaker`.
6. `orchestrator/main.py` — assemble the FastAPI app by merging:
   - **Auth + CORS + SSE + proxy exemptions** from `gateway/app/main.py` (`verify_api_key`,
     `/health`, `/webhooks/*`, `*/stream` exempt). Frontend now calls orchestrator directly, so drop
     the `_proxy` layer and mount the routers instead.
   - **Standup CRUD + templates + SSE stream** routers.
   - **`POST /standups/{id}/start`** (Recall `create_bot`) — copy from `meeting_orchestrator/app/main.py:38-72`.
   - **`POST /webhooks/recall`** — copy the dispatcher from `meeting_orchestrator/app/main.py:116-299`,
     but **replace the transcript.done tail** (`_trigger_summarization` HTTP call at `:282-297`):
     after ingesting utterances, call `await process_standup(standup.id)` (Phase 5.4) which drives the
     A2A summarize→deliver flow. Ingest utterances via the internal function from 5.5 (not an HTTP hop).
   - Keep the SSE generator (`/standups/{id}/stream`) reading `state_transitions`.
**Verify:** run orchestrator + agent + mcp; orchestrator log shows
`A2A skill discovered: summarize_standup / deliver_report` at startup (registry discovery).

## Phase 6 — Dockerfiles, compose, env

1. `Dockerfile.mcp`, `Dockerfile.agent`, `Dockerfile.orchestrator` — base `python:3.11-slim`,
   `COPY shared/ + a2a/ + <component>/ + requirements`, `pip install`, `EXPOSE`, `CMD`
   (mcp: `python mcp_server/standup_tools_server.py`; agent: `uvicorn agent.server:app --port 8020`;
   orchestrator: `uvicorn orchestrator.main:app --port 8000`). Mirror `REF/Dockerfile.slm-sql-agent`
   / `Dockerfile.comms-server`. Requirements per component: fastapi, uvicorn[standard], httpx,
   sqlalchemy[asyncio], asyncpg, pydantic-settings; agent+orchestrator add langgraph, langchain-openai,
   langchain-anthropic, langchain-ollama, mcp==1.26.0, langchain-mcp-adapters==0.2.1; mcp_server adds
   openpyxl, msal, markdown, rapidfuzz.
2. `docker-compose.yml` — REWRITE (mirror `REF/docker-compose.yml` wiring): services `postgres`,
   `migrate`, `standup-mcp` (8010), `standup-agent` (8020, `depends_on standup-mcp healthy`,
   env `MCP_HOST=standup-mcp`), `orchestrator` (8000, env `STANDUP_AGENT_HOST=standup-agent`,
   `MCP_HOST=standup-mcp`, `depends_on standup-agent`), `frontend` (3000). Healthchecks: orchestrator/
   agent `curl /health`; mcp python socket check on 8010. Reuse existing `postgres`/`migrate` blocks.
3. `.env.example` + `.env` — add all Phase-1 vars; keep existing `RECALL_*`, `AZURE_OPENAI_*`,
   `MS_GRAPH_*`, `GATEWAY_API_KEY`, `DATABASE_URL` (still `host.docker.internal:5433` or the compose
   `postgres`).
4. Frontend: point API base at `http://localhost:8000` (was gateway 8000 — same port, so likely no
   change; verify `frontend/src/api/client.ts` + `nginx.conf`).
**Verify:** `docker compose build` succeeds for all 3 new images.

## Phase 7 — Cut over & retire

1. `docker compose up --scale migrate=0` → all healthy.
2. Run the full E2E verification below.
3. Once green, delete `services/gateway`, `services/meeting_orchestrator`,
   `services/transcription_service`, `services/summarization_service`, `services/delivery_service`
   and their compose entries. Keep `services/shared` only if not yet fully moved (prefer top-level
   `shared/`). Update `CLAUDE.md` to the new topology.

## Phase 8 — End-to-end verification (local, no Teams needed)

1. `docker compose up` — orchestrator(8000)/agent(8020)/mcp(8010)/frontend(3000)/postgres healthy.
2. **Discovery:** `curl http://localhost:8020/.well-known/agent-card.json` → 2 skills w/ input schemas;
   orchestrator startup log shows both skills discovered.
3. **Create standup** via UI or `POST /api/standups` (3 participants).
4. **Simulate the meeting** by POSTing canned Recall payloads to `POST /webhooks/recall`
   (`bot.in_call_recording`, then `transcript.done` with a `download_url` or seed utterances via SQL
   from the memory file), OR call `process_standup` directly after seeding utterances.
5. **Assert the chain fired:** orchestrator log → `message/send` to agent (summarize then deliver);
   agent log → MCP tool calls `get_standup_context`, `save_summaries`, `build_excel_report`,
   `send_email`, `record_delivery`; DB has `participant_summaries` + `standup_summaries` +
   `email_deliveries` rows.
6. **Frontend parity:** detail page shows transcript + per-person + rollup; Excel download; resend-email;
   SSE live status still streams.
7. **Model routing:** agent logs show summarize on `SUMMARIZE_MODEL` (gpt-4o), deliver on
   `DELIVER_MODEL`; changing a model is env-only.

---

## Follow-up (separate iteration) — Azure Container Apps
Per-component images → ACR; `.github/workflows/azure-deploy.yml` (mirror REF) doing parallel builds
+ `az containerapp update`; internal ingress for `standup-mcp` + `standup-agent`, external for
`orchestrator` + `frontend`; secrets as Container App env vars; agent/mcp `min-replicas 1`.

## Ground rules recap for the implementer
- Copy A2A/MCP **patterns** from REF; do not add an A2A SDK dependency.
- Keep A2A payloads small (pass `standup_id`; agent pulls bulk data via MCP).
- Preserve the existing Postgres schema and all current API shapes the frontend expects.
- Every phase must pass its **Verify** before moving on.

---

## Reference file index (patterns to copy)

| New file | Copy pattern from (under REF) |
|---|---|
| `a2a/a2a_models.py` | `slm_agents/a2a_models.py` |
| `a2a/a2a_client.py` | `services/a2a_client.py` |
| `a2a/agent_cards.py` | `slm_agents/agent_cards.py` |
| `orchestrator/a2a_registry.py` | `orchestrator/a2a_registry.py` |
| `agent/server.py` | `slm_agents/sql_agent_server.py` |
| `agent/slm_llm_service.py` | `services/slm_llm_service.py` |
| `agent/mcp_config.py` | `slm_agents/sql_agent_server.py` (SQL_SERVER_CONFIG + get_tools) |
| `mcp_server/standup_tools_server.py` | `mcp_servers/comms_server.py` |
| `orchestrator/llm_service.py` | `services/llm_service.py` |
| `docker-compose.yml`, `Dockerfile.*` | REF root `docker-compose.yml`, `Dockerfile.slm-*`, `Dockerfile.*-server` |
| `.github/workflows/azure-deploy.yml` (follow-up) | `.github/workflows/azure-deploy.yml` |

## Existing-app reuse index (functionality to preserve)

| Capability | Reuse from (under APP) |
|---|---|
| Recall bot ops | `services/meeting_orchestrator/app/recall_client.py` |
| Webhook sig verify + dedup | `services/meeting_orchestrator/app/webhooks.py` |
| Meeting state enum/store | `services/meeting_orchestrator/app/state_machine.py` |
| Webhook dispatcher + start | `services/meeting_orchestrator/app/main.py` (`:38-72`, `:116-299`) |
| Standup/template CRUD | `services/meeting_orchestrator/app/routes/{standups,templates}.py` |
| Speaker attribution | `services/transcription_service/app/attribution.py` |
| Transcript reads/ingest | `services/transcription_service/app/routes/utterances.py` |
| Per-person + rollup summaries | `services/summarization_service/app/routes/summaries.py`, `azure_openai_client.py`, `prompts/{per_person,rollup}.py` |
| Excel builder | `services/delivery_service/app/excel_builder.py` |
| MS Graph email | `services/delivery_service/app/graph_client.py` |
| Delivery orchestration | `services/delivery_service/app/routes/delivery.py` |
| Shared models/db/schemas/config | `services/shared/shared/*` |
