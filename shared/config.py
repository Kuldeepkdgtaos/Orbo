from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://standup:standup@postgres:5432/standup"
    gateway_api_key: str = "changeme"
    internal_service_token: str = "changeme-internal"
    log_level: str = "INFO"
    env: str = "local"

    # ── Multi-user auth (JWT) ────────────────────────────────────────────────
    jwt_secret: str = "change-this-jwt-secret"  # MUST be overridden in production
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60 * 24 * 7        # 7 days

    recall_api_key: str = ""
    recall_webhook_secret: str = ""
    recall_region: str = "us-west-2"
    recall_webhook_base_url: str = ""

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_api_version: str = "2024-08-01-preview"

    ms_graph_tenant_id: str = ""
    ms_graph_client_id: str = ""
    ms_graph_client_secret: str = ""
    ms_graph_sender_email: str = ""

    # ── LLM orchestrator (A2A client) ───────────────────────────────────────
    llm_provider: str = "azure_openai"          # azure_openai | anthropic | ollama
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-6"
    ollama_base_url: str = "http://host.docker.internal:11434"
    orchestrator_model: str = "gpt-4o"          # Azure deployment name when llm_provider=azure_openai

    # ── SLM (agent side, provider-configurable per skill) ───────────────────
    slm_provider: str = "azure_openai"          # azure_openai | groq | ollama
    groq_api_key: str = ""
    summarize_model: str = "gpt-4o"             # Azure deployment for summarize_standup skill (quality-critical)
    deliver_model: str = "gpt-4o"               # SLM for deliver_report skill (swap to a smaller model later)

    # ── Agent role (which card + skill set this agent process serves) ────────
    # 'all' (default) → one agent serves BOTH standup + project skills, so a
    # single agent container covers both domains (fewer apps in prod).
    # 'standup' / 'project' remain valid if you ever want to split them again.
    agent_role: str = "all"                     # all | standup | project

    # ── A2A (the single agent the orchestrator talks to) ─────────────────────
    a2a_scheme: str = "http"
    agent_enabled: bool = True
    agent_host: str = "agent"
    agent_port: int = 8020

    # ── MCP (standup-tools server) ───────────────────────────────────────────
    mcp_scheme: str = "http"
    mcp_host: str = "standup-mcp"
    mcp_port: int = 8010

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
