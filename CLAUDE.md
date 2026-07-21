# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture (A2A + MCP)

This app was migrated from a 6-microservice pipeline to a hierarchical **A2A (Agent-to-Agent)
+ MCP (Model Context Protocol)** architecture. See `IMPLEMENTATION_PLAN.md` for the full
migration plan and rationale. The old 6-service implementation, Alembic migrations, and the
empty `tests/` scaffold were all removed after the new stack was verified working end-to-end —
schema management is now a single manual SQL script (`db-setup.sql`), not Alembic.

```
Frontend (React SPA, :3000)  — left nav: Standup Management / Project Management,
      │                          each with Meetings / Data Entry / Summaries
      │  REST + SSE (/api/*, Authorization: Bearer JWT)
      ▼
┌────────────────────────────────────────────────┐
│ ORCHESTRATOR (:8000) — A2A CLIENT                │
│  • multi-user JWT auth, CORS, SSE live status     │
│  • meeting + template CRUD (direct DB, domain-tagged) │
│  • Data Entry: per-user dynamic Postgres tables   │
│  • Insights: historic/aggregate summaries (cache) │
│  • Recall webhook ingress + meeting state machine │
│  • transcript ingest + speaker attribution        │
│  • Tier-1 ReAct agent (LangGraph); routes each     │
│    meeting to its domain's agent by `domain`       │
└───────┬──────────────────────────────┬──────────┘
        │  A2A v0.3.0 (JSON-RPC, /a2a)  │
        ▼                               ▼
┌──────────────────────┐   ┌──────────────────────────┐
│ STANDUP MANAGER AGENT │   │ PROJECT MANAGER AGENT      │
│ (:8020, role=standup) │   │ (:8021, role=project)      │
│ summarize_standup,    │   │ summarize_project,         │
│ deliver_report,       │   │ deliver_project_report,    │
│ summarize_period      │   │ summarize_period           │
└──────────┬───────────┘   └───────────┬──────────────┘
           │  both same image (AGENT_ROLE)│
           │       MCP (streamable-http, POST /mcp)
           ▼                              ▼
┌────────────────────────────────────────────────┐
│ STANDUP-TOOLS MCP SERVER (:8010) — shared         │
│  get_standup_context, save_summaries,             │
│  build_excel_report, send_email, record_delivery, │
│  get_period_context, get_dataentry_context        │
└───────────────┬────────────────────────────────┘
                ▼
          PostgreSQL   (Recall.ai + MS Graph external)
```

Recall.ai webhooks and the frontend both terminate at the orchestrator only — both agents and the
MCP server are internal-only (no ports need to be exposed publicly in production).

**Multi-agent, one image.** The Standup and Project Manager agents run from the *same* `agent/`
image, selected by `AGENT_ROLE` (`standup`|`project`). `a2a/agent_cards.build_agent_card(role)`
is the single source of truth for each role's card + skills; `agent/skills/registry.py` maps skill
ids → handlers per role (replacing the old if/elif dispatch). A meeting's `domain` column decides
which agent processes it (`orchestrator/react_agent.process_meeting`).

**Two domains, shared pipeline.** `standups`/`standup_templates` carry a `domain` column
(`standup`|`project`); project meetings reuse the *same* Recall bot + transcript pipeline and only
differ in the summary lens (PM prompt in `agent/prompts/project_rollup.py`).

**Multi-user auth (JWT).** `orchestrator/auth.py` — bcrypt + JWT bearer, self-serve signup. Only
**Data Entry is per-user** (a dedicated `dataentry_<email>` Postgres schema); meetings, templates
and summaries are **shared** — login just gates access. App-level dependency `require_auth`
enforces the token; exempt paths: `/health`, `/webhooks/*`, `*/stream`, `/api/auth/login|register`.

**Data Entry.** `orchestrator/dataentry_service.py` is the ONLY place that emits dynamic DDL —
real Postgres tables under the user's schema, with **generated opaque identifiers** (`t_<hex>`,
`c_<hex>`) never derived from user input, per-schema metadata tables for display names, and all
values bound as parameters. Routes: `orchestrator/routes/dataentry.py`.

**Insights (historic summaries).** `orchestrator/routes/insights.py` — `GET /insights/meetings`
(call-level, direct DB) and `POST /insights/aggregate` (buckets the range by granularity
overall/monthly/weekly, calls the domain agent's `summarize_period`, caches each bucket in
`aggregate_summaries`; `force` bypasses cache).

**Postgres is external, not part of this compose file.** `docker-compose.yml` only runs the 4
app containers (`standup-mcp`, `standup-agent`, `orchestrator`, `frontend`); `DATABASE_URL` in
`.env` points at a Postgres you run yourself (defaults to `host.docker.internal:5433`).

## Running the Application

```bash
# One-time (and after any schema change): apply the schema to your Postgres.
# Idempotent — safe to re-run any time, never touches existing data.
psql -U postgres -p 5433 -d standup -f db-setup.sql

# Start everything
docker compose up

# Rebuild a single component after code changes
docker compose build orchestrator   # or: standup-agent, project-agent, standup-mcp, frontend
docker compose up -d --no-deps orchestrator

# Frontend dev server (hot reload, proxies /api to localhost:8000)
cd frontend && npm install && npm run dev   # http://localhost:3000

# View logs for a specific component
docker compose logs orchestrator -f
docker compose logs standup-agent -f
docker compose logs standup-mcp -f

# Reset all operational data (leaves users + their Data Entry schemas intact)
docker compose exec postgres psql -U standup -d standup -c "TRUNCATE TABLE email_deliveries, standup_summaries, participant_summaries, aggregate_summaries, utterances, state_transitions, participants, standups CASCADE;"
```

Service ports: `orchestrator=8000`, `standup-agent=8020`, `project-agent=8021`, `standup-mcp=8010`,
`frontend=3000`, `postgres=5432` (compose-local) — **but** `DATABASE_URL` in `.env` defaults to
`host.docker.internal:5433`, i.e. a Postgres instance running on the *host* outside this
compose file. If you want the app to use the compose's own bundled Postgres instead, override
`DATABASE_URL` to `postgresql+asyncpg://standup:standup@postgres:5432/standup` in `.env`.

There is no `requirements.txt`/`pyproject.toml` for any Python component — each `Dockerfile.*`
`pip install`s its own pinned dependency list inline, so Docker is the only supported way to
run `orchestrator/`, `agent/`, or `mcp_server/`; there's no local (non-Docker) dev workflow for
them. There is also no test suite and no linter/formatter configured anywhere in the repo
(frontend or Python) — don't go looking for a `test`/`lint` script to run before calling a
change done.

## Component Responsibilities

### `orchestrator/` — meeting runtime + A2A client (absorbed old gateway + meeting_orchestrator + transcription_service)
- `main.py` — FastAPI app: auth (`X-API-Key`), CORS, all `/api/*` routers, `POST /webhooks/recall`
  (full Recall event dispatcher), `POST /api/standups/{id}/start`, SSE stream.
- `recall_client.py`, `webhooks.py` (Svix signature + dedup), `state_machine.py`,
  `attribution.py` (rapidfuzz speaker matching), `ingest.py` — meeting-lifecycle logic, largely
  unchanged from the pre-migration `meeting_orchestrator`/`transcription_service`.
- `a2a_registry.py` — discovers the Standup Manager Agent's live Agent Card and converts its
  skills into LangChain `StructuredTool`s (dynamic Pydantic models built from `inputSchema`).
- `react_agent.py` — `process_standup(standup_id)`: a Tier-1 `create_react_agent` whose tools
  are the A2A skills. Falls back to calling the two skills directly (no LLM) if the ReAct path
  raises OR if any tool result comes back `{"status": "failed", ...}` — see
  `_extract_tool_failures`. This dual-path design exists because a failed A2A skill call
  returns as a JSON string inside a `ToolMessage`, not as a Python exception, so "the ReAct
  loop finished" and "the skills succeeded" are different conditions that must both be checked.
- `routes/standups.py`, `routes/templates.py` — CRUD, direct DB (unchanged behavior).
- `routes/transcript.py` — utterance reads.
- `routes/summaries.py` — `GET summary` / `participant-summaries` / `excel` are direct DB reads
  (no agent involved — pure, deterministic renders); `POST regenerate` / `deliver` /
  `resend-email` call the agent via A2A (`summarize_standup` / `deliver_report`).

### `agent/` — Standup Manager Agent (A2A server; absorbed old summarization_service + delivery_service reasoning)
- `server.py` — A2A v0.3.0 JSON-RPC dispatcher (`message/send`, `tasks/get`, `tasks/cancel`) +
  `/.well-known/agent-card.json`. In-memory task store (single-instance only, same limitation
  as before the migration).
- `skills/summarize.py` — per-person + rollup summaries via GPT-4o (`gpt4o_client.py`,
  `prompts/`). Always GPT-4o regardless of `SLM_PROVIDER` — this was an explicit
  quality-preserving decision, not left provider-configurable.
- `skills/deliver.py` — builds the Excel report + composes the email + sends it. The SLM
  (`slm_llm_service.create_slm_model`, provider/model configurable via `SLM_PROVIDER`/
  `DELIVER_MODEL`) is used **only** to write a 1–2 sentence email intro, constrained to the
  given facts with a deterministic fallback sentence on failure. The actual digest content
  (wins/blockers/per-person summaries) is always the deterministic GPT-4o rollup —
  the SLM never regenerates or paraphrases it. This was a deliberate scope-narrowing from
  the original migration plan's "SLM composes body" to avoid an LLM fabricating or corrupting
  content in a management-facing email.
- Talks to `standup-mcp` via `langchain_mcp_adapters.MultiServerMCPClient`, calling tools
  directly by name (`mcp_config.call_tool`) rather than through a ReAct loop — both skills are
  fully deterministic pipelines (fetch → reason → save), so there's no benefit to letting an
  LLM choose which tool to call next, only risk (skipped steps, wrong order, hallucinated args).

### `mcp_server/` — standup-tools MCP server (absorbed old delivery_service's deterministic I/O)
- `standup_tools_server.py` — FastMCP, `streamable-http` transport, `stateless_http=True`.
  5 tools, all DB/IO-backed, no LLM reasoning: `get_standup_context`, `save_summaries`,
  `build_excel_report` (also returns rollup fields so `deliver_report` needs only one MCP round
  trip), `send_email` (MS Graph — gracefully returns `{"success": false, "error": ...}` rather
  than raising if `MS_GRAPH_*` isn't configured), `record_delivery`.
- `graph_client.py` — MS Graph email client (moved, unchanged).
- Excel rendering (`shared/excel_builder.py`) lives in the **shared** package, not here, because
  `orchestrator/routes/summaries.py`'s `GET /excel` also needs it for a direct download — keeping
  one copy avoids two images drifting out of sync.

### `a2a/` — hand-rolled A2A v0.3.0 protocol layer (no third-party A2A SDK)
`a2a_models.py` (Task/Message/Part/Artifact/JSON-RPC/AgentCard Pydantic models),
`a2a_client.py` (httpx-based client: `get_agent_card`, `send_message`/`send_task`, `get_task`),
`agent_cards.py` (`STANDUP_AGENT_CARD` — the single source of truth for the agent's 2 skills).

### `shared/` — models, schemas, DB, config (installed nowhere as a package — plain `COPY` +
`ENV PYTHONPATH=/app` in every Dockerfile; each image only imports the submodules it needs, so
e.g. the agent image never pulls in `sqlalchemy`/`asyncpg` since it has no direct DB access).

## Auth

Multi-user JWT (`orchestrator/auth.py`), enforced by the app-level dependency `require_auth` in
`orchestrator/main.py`. Users self-register (`POST /api/auth/register`) → bcrypt-hashed password +
a dedicated `dataentry_<email>` schema; login returns a bearer token the SPA sends as
`Authorization: Bearer`. Exempt paths: `/health`, `/`, `/webhooks/*`, any path ending in `/stream`
(EventSource can't send headers), and `/api/auth/login|register`. `require_auth` stashes the
resolved `User` on `request.state.current_user`; routes needing identity (Data Entry, Insights)
read it via `auth.current_user`. The old static `GATEWAY_API_KEY` gate was replaced by this.

## Docker Build Context

All Dockerfiles use `.` (project root) as build context and `COPY` only the top-level
directories they need (e.g. `Dockerfile.agent` copies `shared/`, `a2a/`, `agent/`). Every
image sets `ENV PYTHONPATH=/app` explicitly — don't rely on implicit CWD-based import
resolution, since how `sys.path` gets populated depends on exactly how the entrypoint
(`uvicorn ...`, `python ...`) is invoked.

## Key Conventions

**State machine states** (`StandupStateEnum`, unchanged): `idle → bot_dispatched → bot_joined →
greeting → asking → listening → next_person → wrap_up → completed | failed`

**Standup statuses** (DB strings, unchanged): `idle | dispatched | in_progress | completed | failed`

**Speaker attribution** (`orchestrator/attribution.py`, unchanged): exact match on
`teams_display_name`, then rapidfuzz fuzzy match at 85% threshold. Unattributed utterances have
`participant_id = NULL`.

**Summarization**: GPT-4o often wraps output in ` ```markdown ``` ` fences — stripped by
`stripCodeFence()` in `frontend/src/components/SummaryPanel.tsx` before rendering.

**`key_wins`/`key_blockers` parsing** (`agent/skills/summarize.py`, carried over unchanged from
before the migration): a naive heuristic — a rollup markdown bullet line only counts as a "win"
or "blocker" if it literally contains that word. GPT-4o's actual phrasing (e.g.
`- **Asha Rao**: Completed the migration script`) often doesn't, so these lists frequently come
back empty even when the rollup text clearly describes wins/blockers. Known pre-existing
weakness, not something the migration changed — worth a follow-up prompt/parsing improvement.

**Recall.ai region**: bot creates at `https://{RECALL_REGION}.recall.ai/api/v1/bot`. Transcript
endpoint is `GET /api/v1/transcript/{transcript_id}/` (the older `/bot/{id}/transcript` is
deprecated, returns 400). `real_time_transcription` is rejected by Recall's current API — the
client auto-retries without it.

**Schema management**: Alembic was removed — `db-setup.sql` is now the single source of truth
for the schema, run manually against whatever Postgres you point `DATABASE_URL` at. It's fully
idempotent (every `CREATE TABLE`/`ALTER TABLE` is guarded), so re-running it after a schema
change is always safe and never touches existing data. (History: the Alembic migrations used
`postgresql.TIMESTAMPTZ`, which a newer SQLAlchemy release removed, breaking `migrate` on any
fresh database — masked for a long time because dev setups pointed at an already-migrated host
Postgres. `db-setup.sql` uses plain `TIMESTAMPTZ` directly in SQL, which never had this problem.)

## Environment

Required `.env` values (see `.env.example`):
- `DATABASE_URL` — defaults to `host.docker.internal:5433`, an external Postgres you run and
  manage yourself (not part of `docker-compose.yml`). Apply the schema once with
  `psql -U postgres -p 5433 -d standup -f db-setup.sql` before starting the app.
- `RECALL_API_KEY`, `RECALL_WEBHOOK_SECRET`, `RECALL_REGION=us-east-1`, `RECALL_WEBHOOK_BASE_URL`
  (ngrok URL) — ngrok must point at host port **8000** (the orchestrator), same as before.
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT=gpt-4o`
- `MS_GRAPH_*` — leave blank to skip email delivery (the `send_email` MCP tool degrades
  gracefully and the failure is recorded in `email_deliveries`, not swallowed silently).
- `JWT_SECRET` (MUST override in production), `JWT_ALGORITHM=HS256`, `JWT_EXPIRY_MINUTES` — multi-user
  auth. `GATEWAY_API_KEY` still exists in config but no longer gates user routes (kept for parity).
- `AGENT_ROLE` (`standup`|`project`) — set per agent container in `docker-compose.yml`, selects the
  card + skill set. Both agents run from the same image.
- New, model/protocol routing (all have working defaults — see `.env.example` for the full list):
  `LLM_PROVIDER`/`ORCHESTRATOR_MODEL` (orchestrator's Tier-1 ReAct model),
  `SLM_PROVIDER`/`SUMMARIZE_MODEL`/`DELIVER_MODEL` (agent skills — `SUMMARIZE_MODEL` should stay
  GPT-4o; `DELIVER_MODEL` is the one meant to be swapped for a smaller model later),
  `STANDUP_AGENT_HOST`/`PORT`, `PROJECT_AGENT_HOST`/`PORT`, `MCP_HOST`/`PORT`.
  `SLM_PROVIDER=groq` requires adding `langchain-groq` to `Dockerfile.agent` — not installed by
  default.

## Frontend

- State: TanStack Query for server data, Zustand (persisted to localStorage) for `apiKey`.
- The `SummaryPanel` polls every 5s until data appears (`refetchInterval: (data) => !data ? 5_000 : false`).
- The `LiveStatusStream` component uses native `EventSource` — cannot send auth headers, so
  `/stream` is auth-exempt.
- `nginx.conf` proxies `/api/` to `orchestrator:8000` (was `gateway:8000` before the migration).
- Build: `vite build` (no separate `tsc` step — Vite handles TypeScript).
- `/features` — static documentation page (features, setup steps, architecture diagram),
  content in `src/content/featuresContent.ts`, rendered with `react-markdown`. No backend
  involvement — pure client-side content, doesn't require the API key to view.

## Not Yet Done (Phase 2 / follow-up items)

- **Azure Container Apps deployment** — local `docker-compose` only for now; a
  GitHub Actions → `az containerapp update` pipeline (mirroring the AskNIKI reference
  architecture) is a separate follow-up, not yet built.
- In-memory state store (`state_machine.py`) and webhook dedup → Redis; agent task store → Redis
  (all single-instance-only today, same limitation as before the migration).
- Voice prompts via Azure TTS, cron scheduling via APScheduler, multi-tenancy, pgvector Q&A.
- `key_wins`/`key_blockers` parsing heuristic (see above) could be made more robust.
