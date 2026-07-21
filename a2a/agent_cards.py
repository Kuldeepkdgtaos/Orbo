"""
A2A v0.3.0 Agent Cards — one per agent *role*.

Two roles run from the same image (agent/server.py), selected by AGENT_ROLE:
  - "standup"  → Standup Manager Agent  (per-person + team rollups)
  - "project"  → Project Manager Agent  (project-level rollups, PM lens)

Both share an aggregate/historic skill (``summarize_period``) whose id is the
same across roles — that's fine because the orchestrator discovers/serves each
agent independently (see a2a_registry.get_tools(agent_name=...)), so the two
never collide inside one tool list.

``build_agent_card(role)`` is the single source of truth for a role's card.
Served at: GET /.well-known/agent-card.json
"""
from a2a.a2a_models import (
    AgentCard, AgentSkill, AgentCapabilities, AgentInterface, AgentProvider,
)

# ── Reusable input-schema fragments ──────────────────────────────────────────

_STANDUP_ID_SCHEMA = {
    "type": "object",
    "required": ["standup_id"],
    "properties": {
        "standup_id": {"type": "string", "description": "UUID of the meeting to summarize"},
    },
}

_DELIVER_SCHEMA = {
    "type": "object",
    "required": ["standup_id"],
    "properties": {
        "standup_id": {"type": "string", "description": "UUID of the meeting to deliver"},
        "force_resend": {
            "type": "boolean",
            "description": "Resend even if a delivery was already recorded",
            "default": False,
        },
    },
}

# Aggregate/historic rollup over a single (already-bucketed) date range. The
# orchestrator's insights route computes granularity buckets and calls this
# once per bucket, caching each result.
_PERIOD_SCHEMA = {
    "type": "object",
    "required": ["domain", "scope", "range_start", "range_end"],
    "properties": {
        "domain": {"type": "string", "description": "'standup' or 'project'"},
        "scope": {"type": "string", "description": "individual | project | overall"},
        "range_start": {"type": "string", "description": "ISO date (inclusive) for this bucket"},
        "range_end": {"type": "string", "description": "ISO date (inclusive) for this bucket"},
        "subject_id": {"type": "string", "description": "participant_id (individual) or template_id (project); omit for overall", "default": ""},
        "subject_label": {"type": "string", "description": "Human name/label for the subject, for prompt phrasing", "default": ""},
        "period_label": {"type": "string", "description": "Human label for the bucket, e.g. 'July 2026', 'week of 2026-07-13', 'overall'", "default": "overall"},
        "dataentry_schema": {"type": "string", "description": "Caller's Data Entry schema, when tables are included", "default": ""},
        "dataentry_table_ids": {"type": "array", "items": {"type": "string"}, "description": "Data Entry table ids to fold into context", "default": []},
    },
}


# ── Per-role skill sets ──────────────────────────────────────────────────────

def _summarize_period_skill() -> AgentSkill:
    return AgentSkill(
        id="summarize_period",
        name="Summarize Period",
        description=(
            "Generate an aggregated summary across all meetings in a date range "
            "for a given scope (individual / project / overall), using GPT-4o. "
            "Reads the in-range call and per-person summaries via MCP tools and "
            "optionally folds in selected Data Entry tables. Returns markdown + "
            "key points. Called once per granularity bucket by the orchestrator."
        ),
        tags=["summarize", "aggregate", "historic", "gpt-4o"],
        examples=[
            "Summarize the team's progress for July 2026",
            "Weekly individual summary for a teammate",
            "Overall project summary for the last month",
        ],
        inputSchema=_PERIOD_SCHEMA,
    )


_STANDUP_SKILLS = [
    AgentSkill(
        id="summarize_standup",
        name="Summarize Standup",
        description=(
            "Generate per-person summaries (yesterday/today/blockers) and a "
            "management rollup digest for a completed standup, using GPT-4o. "
            "Reads the transcript and participant roster via MCP tools, then "
            "persists the summaries. Call this after the meeting has ended and "
            "the transcript has been fully ingested."
        ),
        tags=["summarize", "standup", "gpt-4o", "rollup"],
        examples=[
            "Summarize standup <standup_id>",
            "Generate the digest for today's standup",
            "Regenerate summaries for this standup",
        ],
        inputSchema=_STANDUP_ID_SCHEMA,
    ),
    AgentSkill(
        id="deliver_report",
        name="Deliver Standup Report",
        description=(
            "Build the Excel report (rollup + per-person + full transcript) and "
            "email it to the standup's management recipients. Composes the email "
            "subject/body from the already-generated rollup summary. Requires "
            "summarize_standup to have completed first for this standup."
        ),
        tags=["deliver", "email", "excel", "report"],
        examples=[
            "Send the standup report to management",
            "Resend the email for this standup",
            "Deliver the digest",
        ],
        inputSchema=_DELIVER_SCHEMA,
    ),
    _summarize_period_skill(),
]


_PROJECT_SKILLS = [
    AgentSkill(
        id="summarize_project",
        name="Summarize Project Meeting",
        description=(
            "Generate a project-manager-lens summary of a completed project "
            "meeting using GPT-4o: overall status, progress against goals, risks, "
            "milestones, decisions and blockers at the PROJECT level (not "
            "per-teammate). Reads the transcript + roster via MCP tools and "
            "persists the rollup. Call after the meeting transcript is ingested."
        ),
        tags=["summarize", "project", "gpt-4o", "status"],
        examples=[
            "Summarize project meeting <standup_id>",
            "Generate the project status for this call",
            "Regenerate the project summary",
        ],
        inputSchema=_STANDUP_ID_SCHEMA,
    ),
    AgentSkill(
        id="deliver_project_report",
        name="Deliver Project Report",
        description=(
            "Build the Excel report and email the project status digest to the "
            "meeting's management recipients. Composes the email from the "
            "already-generated project rollup. Requires summarize_project first."
        ),
        tags=["deliver", "email", "excel", "project"],
        examples=[
            "Send the project report to management",
            "Resend the project email",
            "Deliver the project digest",
        ],
        inputSchema=_DELIVER_SCHEMA,
    ),
    _summarize_period_skill(),
]


_ROLE_SKILLS = {
    "standup": _STANDUP_SKILLS,
    "project": _PROJECT_SKILLS,
}

_ROLE_META = {
    "standup": (
        "standup-manager-agent",
        ("Handles post-meeting standup processing: summarizes each participant's "
         "spoken update and the team-wide rollup using GPT-4o, then composes and "
         "delivers the digest (Excel + email). Also produces historic/aggregated "
         "individual and team summaries over a date range."),
    ),
    "project": (
        "project-manager-agent",
        ("Handles project meeting processing with a project-manager lens: "
         "summarizes project status, risks, milestones and blockers (not "
         "per-teammate) using GPT-4o, delivers the digest (Excel + email), and "
         "produces historic/aggregated project summaries over a date range."),
    ),
}


def build_agent_card(role: str) -> AgentCard:
    """Build the AgentCard for a role ('standup' | 'project'). The interface URL
    is left blank here and populated at runtime by agent/server.py."""
    if role not in _ROLE_SKILLS:
        raise ValueError(f"Unknown agent role: {role!r}")
    name, description = _ROLE_META[role]
    return AgentCard(
        name=name,
        description=description,
        version="1.0.0",
        protocolVersion="0.3.0",
        supportedInterfaces=[
            AgentInterface(url="", protocolBinding="JSONRPC", protocolVersion="0.3.0"),
        ],
        provider=AgentProvider(organization="AI Standup Manager"),
        capabilities=AgentCapabilities(
            streaming=False, pushNotifications=False, stateTransitionHistory=True,
        ),
        defaultInputModes=["application/json"],
        defaultOutputModes=["application/json"],
        skills=_ROLE_SKILLS[role],
    )


# Backwards-compatible alias — some tooling/tests import the standup card by name.
STANDUP_AGENT_CARD = build_agent_card("standup")
