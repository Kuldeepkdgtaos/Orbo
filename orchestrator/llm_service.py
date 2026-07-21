"""
Orchestrator LLM factory — model selection for the Tier-1 ReAct agent that
drives the post-meeting A2A flow. Provider-configurable via LLM_PROVIDER;
swapping models (or providers) is an env-only change.
"""
import logging

from shared.config import settings

logger = logging.getLogger(__name__)


def get_orchestrator_model():
    """Create the orchestrator's ReAct model per settings.llm_provider."""
    provider = settings.llm_provider

    if provider == "azure_openai":
        from langchain_openai import AzureChatOpenAI
        model = AzureChatOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_deployment=settings.orchestrator_model,
            temperature=0.1,
        )

    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        model = ChatAnthropic(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            temperature=0.1,
        )

    elif provider == "ollama":
        from langchain_ollama import ChatOllama
        model = ChatOllama(
            model=settings.orchestrator_model,
            base_url=settings.ollama_base_url,
            temperature=0.1,
        )

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider}'. Must be one of: azure_openai, anthropic, ollama"
        )

    logger.info(f"Orchestrator model created (provider={provider}, model={settings.orchestrator_model})")
    return model
