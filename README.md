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
Frontend (SPA, nginx)  ──►  Orchestrator (A2A client, FastAPI)
                                 │  routes each meeting by `domain`
                     ┌───────────┴───────────┐
              Standup Manager Agent     Project Manager Agent   (same image, AGENT_ROLE)
                     └───────────┬───────────┘
                          Standup-Tools MCP server
                                 │
                             PostgreSQL   (+ Recall.ai / MS Graph)
```

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
docker compose up --build     # http://localhost:3000
```

The frontend proxies `/api` and `/webhooks` to the orchestrator via `ORCHESTRATOR_URL`
(defaults to the compose orchestrator). For Recall webhooks in local dev, expose the app with
ngrok and set `RECALL_WEBHOOK_BASE_URL`.

Frontend hot-reload dev server:
```bash
cd frontend && npm install && npm run dev      # proxies /api to :8000
```

## Deploy (Azure Container Apps + NeonDB)

Push to `main` → GitHub Actions builds 4 images to ACR and updates 5 Container Apps. See
[DEPLOY-AZURE.md](DEPLOY-AZURE.md) for one-time infra setup, GitHub secrets/variables, and the
Recall webhook URL. No ngrok in prod — the frontend Container App has a public HTTPS FQDN.

## Tech
FastAPI · LangGraph · Azure OpenAI GPT-4o · MCP (FastMCP) · React + Vite + Tailwind ·
PostgreSQL · Recall.ai · Microsoft Graph · Docker · Azure Container Apps.
