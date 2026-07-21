"""
SLM Model Factory — provider-configurable model creation for agent skills.

Supports:
  SLM_PROVIDER=azure_openai (default) — Azure OpenAI / Azure AI Foundry hosted models.
    Reuses AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY. Only the deployment
    name differs per skill (settings.deliver_model, etc.) — swap models by
    changing env vars, no code changes needed.
  SLM_PROVIDER=groq   — Groq-hosted open-source models.
  SLM_PROVIDER=ollama — Local Ollama models.
"""
import logging

from shared.config import settings

logger = logging.getLogger(__name__)


def create_slm_model(model_name: str, temperature: float = 0.3, max_tokens: int = 800, rate_limiter=None):
    """
    Create a chat model for the configured SLM_PROVIDER.

    Args:
        model_name:   Azure deployment name, or Groq/Ollama model identifier.
        temperature:  Sampling temperature.
        max_tokens:   Max tokens to generate (ignored for azure_openai — see below).
        rate_limiter: Optional LangChain rate limiter (Groq only).

    Returns:
        LangChain chat model instance.
    """
    provider = settings.slm_provider

    if provider == "azure_openai":
        from langchain_openai import AzureChatOpenAI
        # max_tokens is intentionally NOT passed. langchain-openai translates it
        # to max_completion_tokens; some Azure AI Foundry deployments (Mistral-
        # family, etc.) reject that field with HTTP 422. Omitting it lets the
        # deployment use its own default limit — safe for gpt-4o today and for
        # a future smaller-model swap on the same field.
        model = AzureChatOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_deployment=model_name,
            temperature=temperature,
        )

    elif provider == "groq":
        from langchain_groq import ChatGroq
        kwargs = {
            "api_key": settings.groq_api_key,
            "model_name": model_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if rate_limiter:
            kwargs["rate_limiter"] = rate_limiter
        model = ChatGroq(**kwargs)

    elif provider == "ollama":
        from langchain_ollama import ChatOllama
        model = ChatOllama(
            model=model_name,
            base_url=settings.ollama_base_url,
            temperature=temperature,
        )

    else:
        raise ValueError(
            f"Unknown SLM_PROVIDER '{provider}'. Must be one of: azure_openai, groq, ollama"
        )

    logger.info(f"SLM model created (provider={provider}, model={model_name}, temperature={temperature})")
    return model
