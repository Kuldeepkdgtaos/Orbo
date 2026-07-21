# 🪐 Orbo

Orbo is an AI meeting manager. It joins your Microsoft Teams calls (via Recall.ai), transcribes and
attributes speakers, and generates summaries with Azure OpenAI GPT-4o — for **two domains**:

- **Standup Management** — per-person (yesterday / today / blockers) + team rollups.
- **Project Management** — project-level status, risks, milestones and blockers (PM lens).

Each domain has three panels: **Meetings** (set up + run calls), **Data Entry** (your own
Excel-like tables), and **Summaries** (call-level, plus historic/aggregated overall / monthly /
weekly rollups that can fold in your Data Entry tables).

## Architecture (A2A + MCP)

A hierarchical **Agent-to-Agent (A2A) + Model Context Protocol (MCP)** stack:

```
Orchestrator (FastAPI) ── serves the React SPA + /api + /webhooks (single public app)
     │  A2A; routes each meeting by `domain` to the right skill
     ▼
Manager Agent (AGENT_ROLE=all) ── one agent, both standup + project skills
     │  MCP
     ▼
Standup-Tools MCP server ──► PostgreSQL   (+ Recall.ai / MS Graph)
```

Deploys as **3 containers** — orchestrator (public, hosts the UI), agent, mcp.

- **Multi-user auth** (JWT, self-serve signup). Only **Data Entry** is per-user (a dedicated
  `dataentry_<email>` Postgres schema); meetings/summaries are shared.
- **Config is 100% environment-driven** — the same images run locally and in prod with only
  variable *values* changing (see `.env.example`).

Full component detail is in [CLAUDE.md](CLAUDE.md); the migration rationale in
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Run locally

```bash
cp .env.example .env          # fill in Recall / Azure OpenAI / (optional) MS Graph
                              # point DATABASE_URL at your local Postgres
psql -U postgres -p 5433 -d standup -f db-setup.sql   # apply schema (idempotent)
docker compose up --build     # open http://localhost:8000 (orchestrator serves the SPA)
```

The orchestrator serves the built SPA and the API same-origin. For Recall webhooks in local dev,
expose the orchestrator with ngrok and set `RECALL_WEBHOOK_BASE_URL`.

Frontend hot-reload dev server:
```bash
cd frontend && npm install && npm run dev      # http://localhost:3000, proxies /api to :8000
```

## Deploy (Azure Container Apps + NeonDB)

Push to `main` → GitHub Actions builds 3 images to ACR and updates 3 Container Apps. See
[DEPLOY-AZURE.md](DEPLOY-AZURE.md) for one-time infra setup, GitHub secrets/variables, and the
Recall webhook URL. No ngrok in prod — the orchestrator Container App has a public HTTPS FQDN and
serves the UI, API, and webhooks.

## Tech
FastAPI · LangGraph · Azure OpenAI GPT-4o · MCP (FastMCP) · React + Vite + Tailwind ·
PostgreSQL · Recall.ai · Microsoft Graph · Docker · Azure Container Apps.
