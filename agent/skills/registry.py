"""Per-role skill registry.

Replaces the previous hardcoded if/elif dispatch in agent/server.py. Each role
(standup | project) maps skill ids → an async handler with the uniform
signature ``handler(skill_data: dict) -> dict``. server.py picks the registry
for its AGENT_ROLE and dispatches by looking up the ``_skill`` id.

Skill ids match a2a/agent_cards.py exactly (that card is what the orchestrator
discovers). The aggregate skill ``summarize_period`` is shared by both roles.
"""
from agent.skills.summarize import run_summarize
from agent.skills.deliver import run_deliver
from agent.skills.summarize_project import run_summarize_project
from agent.skills.deliver_project import run_deliver_project
from agent.skills.aggregate import run_aggregate


def _require_standup_id(data: dict) -> str:
    sid = data.get("standup_id", "")
    if not sid:
        raise ValueError("Missing required field: standup_id")
    return sid


async def _summarize_standup(data: dict) -> dict:
    return await run_summarize(_require_standup_id(data))


async def _deliver_report(data: dict) -> dict:
    return await run_deliver(_require_standup_id(data), force_resend=data.get("force_resend", False))


async def _summarize_project(data: dict) -> dict:
    return await run_summarize_project(_require_standup_id(data))


async def _deliver_project_report(data: dict) -> dict:
    return await run_deliver_project(_require_standup_id(data), force_resend=data.get("force_resend", False))


async def _summarize_period(data: dict) -> dict:
    return await run_aggregate(data)


_STANDUP_REGISTRY = {
    "summarize_standup": _summarize_standup,
    "deliver_report": _deliver_report,
    "summarize_period": _summarize_period,
}

_PROJECT_REGISTRY = {
    "summarize_project": _summarize_project,
    "deliver_project_report": _deliver_project_report,
    "summarize_period": _summarize_period,
}

_ROLE_REGISTRIES = {
    "standup": _STANDUP_REGISTRY,
    "project": _PROJECT_REGISTRY,
}


def get_registry(role: str) -> dict:
    if role not in _ROLE_REGISTRIES:
        raise ValueError(f"Unknown agent role: {role!r}")
    return _ROLE_REGISTRIES[role]
