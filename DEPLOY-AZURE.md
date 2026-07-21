# Deploying Orbo to Azure Container Apps

One-time infrastructure setup, then every push to `main` auto-deploys via
`.github/workflows/azure-deploy.yml`. Orbo = **4 images / 5 Container Apps**:

| App | Image | Ingress | Target port | Public? |
|---|---|---|---|---|
| orchestrator | `orbo-orchestrator` | internal | 8000 | no |
| standup-agent | `orbo-agent` (role=standup) | internal | 8020 | no |
| project-agent | `orbo-agent` (role=project) | internal | 8020 | no |
| standup-mcp | `orbo-mcp` | internal | 8010 | no |
| frontend | `orbo-frontend` | **external** | 80 | **yes** — the only public app |

The **frontend** is the single public entrypoint; it proxies `/api` and `/webhooks`
to the internal orchestrator. So Recall.ai posts to `https://<frontend-fqdn>/webhooks/recall`.
No ngrok — ACA provides the public HTTPS FQDN.

Prerequisites: Azure CLI (`az`), `psql`, a GitHub repo, and either Docker or `az acr build`.

---

## 1. Database — NeonDB

1. Create a Neon project and a database named `orbo`. (Optionally a separate branch/db for dev.)
2. Copy the **pooled** connection string from Neon (host looks like `ep-xxx-pooler.<region>.aws.neon.tech`).
3. Load the schema once (Neon requires TLS — use the libpq form with `sslmode=require`):
   ```bash
   psql "postgresql://<user>:<pw>@<ep>-pooler.<region>.aws.neon.tech/orbo?sslmode=require" -f db-setup.sql
   ```
4. The value you'll store as the GitHub secret `DATABASE_URL` (asyncpg form):
   ```
   postgresql+asyncpg://<user>:<pw>@<ep>-pooler.<region>.aws.neon.tech/orbo?ssl=require
   ```
   (SQLAlchemy's asyncpg driver takes `ssl=require`; psql uses `sslmode=require`.)

---

## 2. Azure infrastructure (`az` CLI)

```bash
# --- pick your values ---
RG=rg-orbo
LOCATION=eastus
ACR=<yourname>orboacr            # globally-unique, lowercase alphanumeric
ENVN=orbo-env

az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights

az group create -n $RG -l $LOCATION

# Container registry (admin creds are what the pipeline's ACR_USERNAME/PASSWORD use)
az acr create -n $ACR -g $RG --sku Basic --admin-enabled true

# Container Apps environment
az containerapp env create -n $ENVN -g $RG -l $LOCATION
```

### 2a. Seed the images (first push)
The pipeline's deploy step runs `az containerapp update`, which needs the apps to exist —
and apps need an image. Build the 4 images into ACR once (no local Docker needed):
```bash
az acr build -r $ACR -t orbo-orchestrator:prod-latest -f Dockerfile.orchestrator .
az acr build -r $ACR -t orbo-agent:prod-latest        -f Dockerfile.agent .
az acr build -r $ACR -t orbo-mcp:prod-latest          -f Dockerfile.mcp .
az acr build -r $ACR -t orbo-frontend:prod-latest     -f frontend/Dockerfile frontend
```

### 2b. Create the 5 apps
```bash
ACR_SERVER=$ACR.azurecr.io
ACR_USER=$(az acr credential show -n $ACR --query username -o tsv)
ACR_PASS=$(az acr credential show -n $ACR --query 'passwords[0].value' -o tsv)
REG="--registry-server $ACR_SERVER --registry-username $ACR_USER --registry-password $ACR_PASS"

# internal apps
az containerapp create -n orbo-mcp -g $RG --environment $ENVN $REG \
  --image $ACR_SERVER/orbo-mcp:prod-latest --ingress internal --target-port 8010 \
  --min-replicas 0 --max-replicas 2

az containerapp create -n orbo-standup-agent -g $RG --environment $ENVN $REG \
  --image $ACR_SERVER/orbo-agent:prod-latest --ingress internal --target-port 8020 \
  --min-replicas 0 --max-replicas 2 --env-vars AGENT_ROLE=standup

az containerapp create -n orbo-project-agent -g $RG --environment $ENVN $REG \
  --image $ACR_SERVER/orbo-agent:prod-latest --ingress internal --target-port 8020 \
  --min-replicas 0 --max-replicas 2 --env-vars AGENT_ROLE=project

az containerapp create -n orbo-orchestrator -g $RG --environment $ENVN $REG \
  --image $ACR_SERVER/orbo-orchestrator:prod-latest --ingress internal --target-port 8000 \
  --min-replicas 1 --max-replicas 3

# public app
az containerapp create -n orbo-frontend -g $RG --environment $ENVN $REG \
  --image $ACR_SERVER/orbo-frontend:prod-latest --ingress external --target-port 80 \
  --min-replicas 1 --max-replicas 2
```
The full env-var wiring is applied by the pipeline on every deploy — you don't need to set it here.

### 2c. Service principal → `AZURE_CREDENTIALS`
```bash
SUB=$(az account show --query id -o tsv)
az ad sp create-for-rbac --name orbo-deploy \
  --role contributor \
  --scopes /subscriptions/$SUB/resourceGroups/$RG \
  --sdk-auth
```
Copy the JSON output → GitHub secret `AZURE_CREDENTIALS`.

---

## 3. GitHub configuration (single `production` Environment)

**Repo → Settings → Secrets and variables → Actions**

Repo **Variables**: `ACR_NAME` = `<yourname>orboacr`
Repo **Secrets**: `ACR_USERNAME`, `ACR_PASSWORD` (from `az acr credential show -n $ACR`).

**Repo → Settings → Environments → New environment → `production`**

Environment **Secrets**:
`AZURE_CREDENTIALS`, `DATABASE_URL` (asyncpg Neon URL), `JWT_SECRET` (long random),
`RECALL_API_KEY`, `RECALL_WEBHOOK_SECRET`, `AZURE_OPENAI_API_KEY`,
`MS_GRAPH_TENANT_ID`, `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_CLIENT_SECRET`.

Environment **Variables**:
`RESOURCE_GROUP`=rg-orbo, `ORCHESTRATOR_APP`=orbo-orchestrator, `STANDUP_AGENT_APP`=orbo-standup-agent,
`PROJECT_AGENT_APP`=orbo-project-agent, `MCP_APP`=orbo-mcp, `FRONTEND_APP`=orbo-frontend,
`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`=gpt-4o, `AZURE_OPENAI_API_VERSION`=2024-08-01-preview,
`RECALL_REGION`, `MS_GRAPH_SENDER_EMAIL`, `LLM_PROVIDER`=azure_openai, `ORCHESTRATOR_MODEL`=gpt-4o,
`SLM_PROVIDER`=azure_openai, `SUMMARIZE_MODEL`=gpt-4o, `DELIVER_MODEL`=gpt-4o,
`JWT_ALGORITHM`=HS256, `JWT_EXPIRY_MINUTES`=10080, `LOG_LEVEL`=INFO.

---

## 4. First deploy

Push to `main` (or run the workflow via **Actions → Run workflow**). The pipeline builds the 4
images, then `az containerapp update`s all 5 apps with the full env set, wiring internal FQDNs +
`443`/`https` automatically and pointing the frontend at the orchestrator.

Get the public URL:
```bash
az containerapp show -n orbo-frontend -g rg-orbo --query properties.configuration.ingress.fqdn -o tsv
```

---

## 5. Point Recall.ai at the webhook

In Recall.ai, set the webhook URL to:
```
https://<frontend-fqdn>/webhooks/recall
```
The frontend proxies it to the internal orchestrator. (This FQDN is stable, unlike ngrok.)

---

## Notes
- **Cold starts**: agents + mcp scale to zero; the orchestrator's 3-retry post-meeting trigger
  tolerates the first-hit wake-up. Orchestrator + frontend stay warm (`min-replicas 1`).
- **SSE**: ACA ingress caps long-lived requests; the live-status stream reconnects automatically.
- **Data Entry schemas** (`dataentry_<email>`) are created at registration time inside NeonDB —
  nothing extra to provision.
