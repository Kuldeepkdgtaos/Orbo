# Deploying Orbo to Azure Container Apps — from zero

This is a complete runbook assuming you have **only an Azure subscription** and nothing else.
Do sections 0–8 **once**; after that, every push to `main` auto-deploys via
`.github/workflows/azure-deploy.yml`.

Orbo = **3 images / 3 Container Apps**:

| App | Image | Ingress | Target port | Public? |
|---|---|---|---|---|
| orchestrator | `orbo-orchestrator` | **external** | 8000 | **yes** — serves the SPA + `/api` + `/webhooks` |
| agent | `orbo-agent` (`AGENT_ROLE=all`) | internal | 8020 | no — one agent, both domains |
| mcp | `orbo-mcp` | internal | 8010 | no |

The **orchestrator** is the single public app: it serves the built React SPA *and* the API *and*
the Recall webhook (same origin), so Recall.ai posts to `https://<orchestrator-fqdn>/webhooks/recall`.
No ngrok — ACA gives a permanent public HTTPS FQDN. (No separate frontend app; no separate
project-agent — one `agent` serves standup + project skills.)

**Checklist:** ☐ tools ☐ Azure login ☐ Neon DB ☐ Recall.ai keys ☐ Azure OpenAI ☐ (opt) MS Graph
☐ RG/ACR/env ☐ build images ☐ create 3 apps ☐ service principal ☐ GitHub secrets/vars ☐ deploy
☐ Recall webhook ☐ verify.

---

## 0. Install tools + sign in

Install locally (Windows: `winget install`, or the linked installers):
- **Azure CLI** — https://aka.ms/installazurecli  (`az version` to check)
- **Git** and **GitHub CLI** (`gh`) — https://cli.github.com
- **psql** (PostgreSQL client) — to load the schema into Neon
- Docker is **optional** (we build images in the cloud with `az acr build`).

```bash
az login                              # opens a browser
az account list -o table              # find your subscription
az account set --subscription "<YOUR-SUBSCRIPTION-NAME-OR-ID>"
az account show -o table              # confirm the active subscription

# Register the resource providers this deployment uses (one-time per subscription)
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.CognitiveServices
# add the Container Apps CLI extension
az extension add --name containerapp --upgrade
```

Pick names now and reuse them throughout (must be globally unique where noted):
```bash
RG=rg-orbo
LOCATION=eastus
ACR=<yourname>orboacr        # ACR name: 5-50 lowercase alphanumeric, GLOBALLY UNIQUE
ENVN=orbo-env
AOAI=<yourname>-orbo-openai  # Azure OpenAI resource name, GLOBALLY UNIQUE
```

```bash
az group create -n $RG -l $LOCATION
```

---

## 1. Database — NeonDB (free managed Postgres)

1. Sign up at https://neon.tech and create a project; inside it, create a database named `orbo`.
2. In the Neon dashboard → **Connection Details**, copy the **pooled** connection string (host looks
   like `ep-xxx-pooler.<region>.aws.neon.tech`).
3. Load Orbo's schema once (Neon requires TLS; psql uses `sslmode=require`):
   ```bash
   psql "postgresql://<user>:<pw>@<ep>-pooler.<region>.aws.neon.tech/orbo?sslmode=require" -f db-setup.sql
   ```
4. Note the **asyncpg** form of the URL — this becomes the GitHub secret `DATABASE_URL`:
   ```
   postgresql+asyncpg://<user>:<pw>@<ep>-pooler.<region>.aws.neon.tech/orbo?ssl=require
   ```
   (SQLAlchemy's asyncpg driver takes `ssl=require`; psql uses `sslmode=require`.)

---

## 2. Recall.ai (bot + transcripts)

1. Sign up at https://recall.ai and grab your **API key** (Settings → API Keys). → `RECALL_API_KEY`.
2. Note your region (e.g. `us-east-1`). → `RECALL_REGION`.
3. You'll create the webhook + its **signing secret** in **section 9** (after the app has a public
   URL). That signing secret becomes `RECALL_WEBHOOK_SECRET`.

---

## 3. Azure OpenAI (GPT-4o)

If you already have an Azure OpenAI resource with a `gpt-4o` deployment, **reuse it** (just grab its
endpoint + key) and skip to section 4. Otherwise create one:

```bash
az cognitiveservices account create -n $AOAI -g $RG -l $LOCATION \
  --kind OpenAI --sku S0 --custom-domain $AOAI --yes

# Deploy the gpt-4o model (adjust --model-version to one available in your region)
az cognitiveservices account deployment create -g $RG -n $AOAI \
  --deployment-name gpt-4o --model-name gpt-4o --model-version 2024-08-06 \
  --model-format OpenAI --sku-name Standard --sku-capacity 10

# Grab the endpoint + key (save these)
az cognitiveservices account show -n $AOAI -g $RG --query properties.endpoint -o tsv
az cognitiveservices account keys list -n $AOAI -g $RG --query key1 -o tsv
```
→ endpoint = `AZURE_OPENAI_ENDPOINT`, key = `AZURE_OPENAI_API_KEY`, deployment name = `gpt-4o`.

> Azure OpenAI may require access approval on some subscriptions, and model availability/quota
> varies by region. If `deployment create` fails, pick a region/version from the Azure AI Foundry
> portal or request quota there.

---

## 4. Microsoft Graph email (OPTIONAL — skip to leave email delivery disabled)

Orbo emails the digest via MS Graph. Leave these blank to skip (delivery degrades gracefully and is
recorded as failed). To enable, in the Azure Portal:
1. **Entra ID → App registrations → New registration** (single tenant is fine).
2. **API permissions → Add → Microsoft Graph → Application permissions → `Mail.Send`** → **Grant
   admin consent**.
3. **Certificates & secrets → New client secret** → copy the value.
4. Collect: Directory (tenant) ID, Application (client) ID, the secret, and a sender mailbox address.
   → `MS_GRAPH_TENANT_ID`, `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_CLIENT_SECRET`, `MS_GRAPH_SENDER_EMAIL`.

---

## 5. Container registry + Container Apps environment

```bash
# Registry (admin creds are what the pipeline's ACR_USERNAME/PASSWORD use)
az acr create -n $ACR -g $RG --sku Basic --admin-enabled true

# Container Apps environment (creates a Log Analytics workspace automatically)
az containerapp env create -n $ENVN -g $RG -l $LOCATION
```

---

## 6. Build the 3 images into ACR

The apps need images to exist before `az containerapp update` (the pipeline) can run. Build the 3
images (the orchestrator image also builds the SPA) and push them to ACR.

> ⚠️ **`az acr build` may be blocked on your subscription** with
> `TasksOperationsNotAllowed` — it uses server-side **ACR Tasks**, which are disabled on many
> free-trial / sponsored / student / CSP subscriptions. If so, use **Option A** (local Docker) or
> **Option B** (the GitHub pipeline) below. `az acr build` is only the convenient path when Tasks
> are enabled.

### Option A — build locally with Docker, push to ACR (works regardless of ACR Tasks)
On a machine with a running Docker daemon (your laptop with Docker Desktop) — **not Azure Cloud
Shell, which has no Docker daemon** — from the repo root.

Log in to ACR. If the Azure CLI is installed locally: `az acr login -n <acr>`. If it isn't,
log in with the ACR **admin** credentials (no `az` needed — enable Admin user in the Portal under
the registry's Access keys, or run `az acr credential show -n <acr>` in Cloud Shell to read them):
```bash
docker login <acr>.azurecr.io          # username + password = ACR admin credentials
docker build -t <acr>.azurecr.io/orbo-orchestrator:prod-latest -f Dockerfile.orchestrator .
docker build -t <acr>.azurecr.io/orbo-agent:prod-latest        -f Dockerfile.agent .
docker build -t <acr>.azurecr.io/orbo-mcp:prod-latest          -f Dockerfile.mcp .
docker push <acr>.azurecr.io/orbo-orchestrator:prod-latest
docker push <acr>.azurecr.io/orbo-agent:prod-latest
docker push <acr>.azurecr.io/orbo-mcp:prod-latest
```
Container Apps run linux/amd64; on an amd64 host no `--platform` flag is needed (on Apple Silicon
add `--platform linux/amd64`). Verify: `az acr repository list -n <acr> -o table` (or the Portal →
registry → Repositories).

### Option B — let the GitHub Actions pipeline build them (no local Docker, no ACR Tasks)
The pipeline builds on GitHub runners and pushes to ACR (unaffected by ACR Tasks). Do §8's GitHub
config first (at least `ACR_NAME` var + `ACR_USERNAME`/`ACR_PASSWORD` secrets), then **Actions → Run
workflow**. The 3 build jobs push the images; the deploy job will fail until the apps exist (§7) —
that's expected. After §7, re-run the workflow so deploy succeeds.

### Option C — `az acr build` (only if ACR Tasks are enabled on your subscription)
Run from inside a clone of the repo (`.` = the build context):
```bash
git clone https://github.com/Kuldeepkdgtaos/Orbo.git && cd Orbo   # username + PAT for the private repo
az acr build -r $ACR -t orbo-orchestrator:prod-latest -f Dockerfile.orchestrator .
az acr build -r $ACR -t orbo-agent:prod-latest        -f Dockerfile.agent .
az acr build -r $ACR -t orbo-mcp:prod-latest          -f Dockerfile.mcp .
```

---

## 7. Create the 3 Container Apps

> Run in **Cloud Shell**. The commands below are **single-line with placeholders** so they work in
> both Bash *and* PowerShell (the `$VAR` + `\`-continuation + `$REG`-splat style is bash-only).
> Replace `<RG>` (resource group), `<ENV>` (Container Apps env), `<ACR_USER>`/`<ACR_PASS>` with your
> values:
>
> ```bash
> az acr show -n <acr> --query resourceGroup -o tsv     # -> <RG>
> az containerapp env list -o table                     # -> <ENV>  (create with `az containerapp env create -n orbo-env -g <RG> -l eastus` if none)
> az acr credential show -n <acr>                        # -> <ACR_USER> + <ACR_PASS>
> ```

```bash
# internal: tools
az containerapp create -n orbo-mcp -g <RG> --environment <ENV> --image <acr>.azurecr.io/orbo-mcp:prod-latest --ingress internal --target-port 8010 --min-replicas 0 --max-replicas 2 --registry-server <acr>.azurecr.io --registry-username <ACR_USER> --registry-password <ACR_PASS>

# internal: one agent, both domains
az containerapp create -n orbo-agent -g <RG> --environment <ENV> --image <acr>.azurecr.io/orbo-agent:prod-latest --ingress internal --target-port 8020 --min-replicas 0 --max-replicas 2 --registry-server <acr>.azurecr.io --registry-username <ACR_USER> --registry-password <ACR_PASS> --env-vars AGENT_ROLE=all

# public: orchestrator serves the SPA + /api + /webhooks
az containerapp create -n orbo-orchestrator -g <RG> --environment <ENV> --image <acr>.azurecr.io/orbo-orchestrator:prod-latest --ingress external --target-port 8000 --min-replicas 1 --max-replicas 3 --registry-server <acr>.azurecr.io --registry-username <ACR_USER> --registry-password <ACR_PASS>
```
The full per-app env-var wiring is applied by the pipeline on every deploy — you don't set it here.

Grab the public URL (used in section 9 for the Recall webhook and to open the app):
```bash
az containerapp show -n orbo-orchestrator -g <RG> --query properties.configuration.ingress.fqdn -o tsv
```

---

## 8. Service principal + GitHub configuration

### 8a. Service principal → `AZURE_CREDENTIALS`
```bash
SUB=$(az account show --query id -o tsv)
az ad sp create-for-rbac --name orbo-deploy \
  --role contributor \
  --scopes /subscriptions/$SUB/resourceGroups/$RG \
  --sdk-auth
```
Copy the **entire JSON** output — it's the `AZURE_CREDENTIALS` secret.

### 8b. GitHub secrets + variables
Set them in the UI (**Settings → Secrets and variables → Actions**, and **Settings → Environments →
New environment → `production`**), or scripted with the `gh` CLI from the repo root:

```bash
gh auth login

# --- Repo-level (shared) ---
gh variable set ACR_NAME     --body "$ACR"
gh secret   set ACR_USERNAME --body "$(az acr credential show -n $ACR --query username -o tsv)"
gh secret   set ACR_PASSWORD --body "$(az acr credential show -n $ACR --query 'passwords[0].value' -o tsv)"

# --- Environment 'production' — SECRETS ---
gh secret set AZURE_CREDENTIALS      --env production --body '<paste the sdk-auth JSON>'
gh secret set DATABASE_URL           --env production --body 'postgresql+asyncpg://…?ssl=require'
gh secret set JWT_SECRET             --env production --body "<64-char random>"
#   generate the value with:  python -c "import secrets; print(secrets.token_hex(32))"
#   (openssl is not available in Windows PowerShell)
gh secret set RECALL_API_KEY         --env production --body '<recall api key>'
gh secret set RECALL_WEBHOOK_SECRET  --env production --body '<set after section 9>'
gh secret set AZURE_OPENAI_API_KEY   --env production --body '<aoai key>'
gh secret set MS_GRAPH_TENANT_ID     --env production --body '<or empty>'
gh secret set MS_GRAPH_CLIENT_ID     --env production --body '<or empty>'
gh secret set MS_GRAPH_CLIENT_SECRET --env production --body '<or empty>'

# --- Environment 'production' — VARIABLES ---
gh variable set RESOURCE_GROUP           --env production --body "$RG"
gh variable set ORCHESTRATOR_APP         --env production --body "orbo-orchestrator"
gh variable set AGENT_APP                --env production --body "orbo-agent"
gh variable set MCP_APP                  --env production --body "orbo-mcp"
gh variable set AZURE_OPENAI_ENDPOINT    --env production --body '<aoai endpoint>'
gh variable set AZURE_OPENAI_DEPLOYMENT  --env production --body "gpt-4o"
gh variable set AZURE_OPENAI_API_VERSION --env production --body "2024-08-01-preview"
gh variable set RECALL_REGION            --env production --body "us-east-1"
gh variable set MS_GRAPH_SENDER_EMAIL    --env production --body '<or empty>'
gh variable set LLM_PROVIDER             --env production --body "azure_openai"
gh variable set ORCHESTRATOR_MODEL       --env production --body "gpt-4o"
gh variable set SLM_PROVIDER             --env production --body "azure_openai"
gh variable set SUMMARIZE_MODEL          --env production --body "gpt-4o"
gh variable set DELIVER_MODEL            --env production --body "gpt-4o"
gh variable set JWT_ALGORITHM            --env production --body "HS256"
gh variable set JWT_EXPIRY_MINUTES       --env production --body "10080"
gh variable set LOG_LEVEL                --env production --body "INFO"
```
> `RECALL_WEBHOOK_SECRET` can be set now with a placeholder and updated after section 9; the app
> only needs it when verifying incoming webhooks.

---

## 9. First deploy + Recall webhook

1. **Deploy**: push to `main` (or **Actions → Build and Deploy → Run workflow**). The pipeline builds
   the 3 images and `az containerapp update`s all 3 apps, wiring the internal FQDNs + `443`/`https`
   and setting the orchestrator's own FQDN as the Recall webhook base.
2. **Open the app** at `https://<orchestrator-fqdn>` and register a user.
3. **Recall webhook**: in Recall.ai, add a webhook pointing to
   ```
   https://<orchestrator-fqdn>/webhooks/recall
   ```
   Copy its **signing secret** → update the `RECALL_WEBHOOK_SECRET` GitHub secret → re-run the
   workflow (or `az containerapp update` the orchestrator) so it picks up the new value.

---

## 10. Verify end-to-end
- `https://<orchestrator-fqdn>` loads the app; register/login works (confirms orchestrator + Neon).
- In Neon, `\dt` shows the Orbo tables and a `dataentry_<email>` schema after signup.
- Create a meeting, start it — the Recall bot joins; after it ends, a summary appears
  (agent + mcp wake from scale-to-zero; watch `az containerapp logs show -n orbo-orchestrator -g $RG`).
- Data Entry: create a table + a row → persists to your Neon schema.
- Summaries: generate an aggregate over a date range.

---

## Notes & troubleshooting
- **Cold starts**: the agent + mcp scale to zero; the orchestrator's 3-retry post-meeting trigger
  tolerates first-hit wake-ups. The orchestrator (public app) stays warm (`min-replicas 1`).
- **SSE**: ACA ingress caps long-lived requests; the live-status stream reconnects automatically.
- **Logs**: `az containerapp logs show -n <app> -g $RG --follow`.
- **Redeploy manually**: `az containerapp update -n <app> -g $RG --image $ACR.azurecr.io/<img>:prod-latest`.
- **First pipeline run before apps exist** will fail at the deploy step — that's why sections 5–7
  create the apps first. The build jobs still succeed and push images.
