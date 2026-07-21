"""
GPT-4o client for the summarize_standup skill.

This is deliberately a dedicated Azure OpenAI client (not the generic
create_slm_model() factory) because summarization requires JSON-mode
structured output (response_format={"type": "json_object"}) for the
per-person extraction, and quality here is explicitly GPT-4o-only per the
architecture decision (SLM is used elsewhere, not for summaries). Logic is
carried over unchanged from the pre-migration summarization service.
"""
import json
import logging
from typing import Optional

from openai import AsyncAzureOpenAI

from shared.config import settings
from agent.prompts.per_person import (
    SYSTEM as PER_PERSON_SYSTEM, USER_TEMPLATE as PER_PERSON_USER_TEMPLATE,
    build_context_line, build_manager_line, build_team_roster_for_person,
)
from agent.prompts.rollup import (
    SYSTEM as ROLLUP_SYSTEM, USER_TEMPLATE as ROLLUP_USER_TEMPLATE,
    build_manager_context, build_full_roster,
)
from agent.prompts.project_rollup import (
    SYSTEM as PROJECT_SYSTEM, USER_TEMPLATE as PROJECT_USER_TEMPLATE,
)
from agent.prompts.aggregate import (
    SYSTEM as AGGREGATE_SYSTEM, USER_TEMPLATE as AGGREGATE_USER_TEMPLATE,
    build_scope_instructions, build_items_block, build_data_entry_block,
)

logger = logging.getLogger(__name__)

_client: AsyncAzureOpenAI | None = None


def get_client() -> AsyncAzureOpenAI:
    global _client
    if _client is None:
        _client = AsyncAzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
    return _client


async def summarize_person(
    name: str,
    date: str,
    transcript: str,
    designation: Optional[str] = None,
    department: Optional[str] = None,
    manager_name: str = "",
    team_roster: str = "",
) -> dict:
    client = get_client()
    context_line = build_context_line(designation, department)
    manager_line = build_manager_line(manager_name)
    user_msg = PER_PERSON_USER_TEMPLATE.format(
        name=name,
        date=date,
        transcript=transcript,
        context_line=context_line,
        manager_line=manager_line,
        team_roster=team_roster,
    )
    response = await client.chat.completions.create(
        model=settings.summarize_model,
        messages=[{"role": "system", "content": PER_PERSON_SYSTEM}, {"role": "user", "content": user_msg}],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=500,
    )
    raw = response.choices[0].message.content or "{}"
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse per-person summary JSON", extra={"raw": raw})
        result = {"yesterday": "", "today": "", "blockers": ""}
    return result


async def summarize_rollup(
    team_name: str,
    date: str,
    joined_summaries: str,
    n: int,
    manager_name: str = "",
    manager_designation: str = "",
    manager_department: str = "",
    team_roster: str = "",
) -> str:
    client = get_client()
    manager_context = build_manager_context(manager_name, manager_designation, manager_department)
    for_manager = f" for {manager_name}" if manager_name else ""
    user_msg = ROLLUP_USER_TEMPLATE.format(
        team_name=team_name,
        date=date,
        n=n,
        manager_context=manager_context,
        team_roster=team_roster,
        joined_summaries=joined_summaries,
        for_manager=for_manager,
    )
    response = await client.chat.completions.create(
        model=settings.summarize_model,
        messages=[{"role": "system", "content": ROLLUP_SYSTEM}, {"role": "user", "content": user_msg}],
        temperature=0.2,
        max_tokens=1200,
    )
    return response.choices[0].message.content or ""


async def summarize_project_rollup(
    team_name: str,
    date: str,
    joined_summaries: str,
    n: int,
    manager_name: str = "",
    manager_designation: str = "",
    manager_department: str = "",
    team_roster: str = "",
) -> str:
    """Project-manager-lens rollup for a single project meeting (project-level
    status, not per-teammate). Mirrors summarize_rollup but with the PM prompt."""
    client = get_client()
    manager_context = build_manager_context(manager_name, manager_designation, manager_department)
    for_manager = f" for {manager_name}" if manager_name else ""
    user_msg = PROJECT_USER_TEMPLATE.format(
        team_name=team_name,
        date=date,
        n=n,
        manager_context=manager_context,
        team_roster=team_roster,
        joined_summaries=joined_summaries,
        for_manager=for_manager,
    )
    response = await client.chat.completions.create(
        model=settings.summarize_model,
        messages=[{"role": "system", "content": PROJECT_SYSTEM}, {"role": "user", "content": user_msg}],
        temperature=0.2,
        max_tokens=1200,
    )
    return response.choices[0].message.content or ""


async def summarize_period_aggregate(
    domain: str,
    scope: str,
    period_label: str,
    range_start: str,
    range_end: str,
    items: list[dict],
    subject_label: str = "",
    data_entry_tables: list[dict] | None = None,
) -> str:
    """Aggregate multiple per-meeting summaries in a date range into one markdown
    rollup at the given scope (individual | project | overall)."""
    client = get_client()
    user_msg = AGGREGATE_USER_TEMPLATE.format(
        domain=domain,
        scope=scope,
        period_label=period_label,
        range_start=range_start,
        range_end=range_end,
        n=len(items),
        scope_instructions=build_scope_instructions(scope, subject_label),
        items=build_items_block(items),
        data_entry_block=build_data_entry_block(data_entry_tables or []),
    )
    response = await client.chat.completions.create(
        model=settings.summarize_model,
        messages=[{"role": "system", "content": AGGREGATE_SYSTEM}, {"role": "user", "content": user_msg}],
        temperature=0.2,
        max_tokens=1500,
    )
    return response.choices[0].message.content or ""
