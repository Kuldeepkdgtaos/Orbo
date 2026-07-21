"""
process_meeting — drives the post-meeting flow (summarize → deliver) once a
meeting's transcript has been fully ingested. Domain-aware: a 'standup' meeting
is processed by the Standup Manager Agent (summarize_standup → deliver_report),
a 'project' meeting by the Project Manager Agent (summarize_project →
deliver_project_report).

Primary path: a Tier-1 ReAct agent (LangGraph's create_react_agent) whose tools
are the relevant agent's A2A skills, discovered live via agent_registry
(scoped to that one agent so skill lists never collide).

Fallback: if the ReAct path raises for any reason (agent unreachable, LLM
provider misconfigured, tool-call malformed, etc.), call the two A2A skills
directly and in order. Correctness of the summarize → deliver sequence matters
more than flexibility here, so a broken orchestrator LLM must never silently
drop a meeting's summary/delivery.
"""
import json
import logging

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from .a2a_registry import agent_registry
from .llm_service import get_orchestrator_model

logger = logging.getLogger(__name__)

# Per-domain routing: both domains are served by the single "agent" (role=all);
# only the skill names differ by domain.
_DOMAIN_ROUTING = {
    "standup": {
        "agent": "agent",
        "summarize": "summarize_standup",
        "deliver": "deliver_report",
    },
    "project": {
        "agent": "agent",
        "summarize": "summarize_project",
        "deliver": "deliver_project_report",
    },
}

PROCESS_PROMPT = (
    "A {domain} meeting with id {standup_id} has just ended and its transcript has "
    "been ingested. Call the {summarize} tool with standup_id=\"{standup_id}\" to "
    "generate the summaries, then call the {deliver} tool with the same standup_id "
    "to email the report to management. Call both tools, in that exact order, "
    "exactly once each. Do not call any other tools."
)


def _routing(domain: str) -> dict:
    return _DOMAIN_ROUTING.get(domain, _DOMAIN_ROUTING["standup"])


def _extract_tool_failures(messages: list) -> list[str]:
    """
    Scan ReAct loop ToolMessages for skill-level failures.

    a2a_registry.invoke_skill() never raises on a failed A2A task — it returns
    a JSON string like {"status": "failed", "error": "..."} so the LLM can see
    and react to it. That means failures don't surface as exceptions here;
    they have to be pulled out of the tool results explicitly.
    """
    failures = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        try:
            payload = json.loads(msg.content)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("status") == "failed":
            failures.append(f"{msg.name}: {payload.get('error', 'unknown error')}")
    return failures


def _task_state_value(task) -> str:
    state = task.status.state
    return state if isinstance(state, str) else state.value


def _task_error_message(task) -> str:
    if task.status.message and task.status.message.parts:
        for part in task.status.message.parts:
            p = part if isinstance(part, dict) else part.model_dump()
            if p.get("kind") == "text":
                return p.get("text", "Unknown error")
    return "Unknown error"


async def _run_deterministic(standup_id: str, domain: str) -> dict:
    """Call the domain's summarize then deliver skill directly, in order, no LLM."""
    route = _routing(domain)
    client = agent_registry.get_client(route["agent"])
    if client is None:
        logger.error("No A2A client registered — cannot process meeting",
                     extra={"standup_id": standup_id, "agent": route["agent"]})
        return {"status": "failed", "step": "discovery", "error": f"{route['agent']} not configured"}

    summarize_task = await client.send_task({"_skill": route["summarize"], "standup_id": standup_id})
    if _task_state_value(summarize_task) != "completed":
        error = _task_error_message(summarize_task)
        logger.error("Deterministic summarize failed", extra={"standup_id": standup_id, "error": error})
        return {"status": "failed", "step": route["summarize"], "error": error}

    deliver_task = await client.send_task({"_skill": route["deliver"], "standup_id": standup_id})
    if _task_state_value(deliver_task) != "completed":
        error = _task_error_message(deliver_task)
        logger.error("Deterministic deliver failed", extra={"standup_id": standup_id, "error": error})
        return {"status": "failed", "step": route["deliver"], "error": error}

    logger.info("process_meeting (deterministic) complete", extra={"standup_id": standup_id, "domain": domain})
    return {"status": "completed"}


async def process_meeting(standup_id: str, domain: str = "standup") -> dict:
    """Drive summarize → deliver for a completed meeting, routed by domain."""
    route = _routing(domain)
    try:
        tools = await agent_registry.get_tools(agent_name=route["agent"])
        if not tools:
            logger.warning(
                "No A2A skills discovered — falling back to deterministic call",
                extra={"standup_id": standup_id, "domain": domain},
            )
            return await _run_deterministic(standup_id, domain)

        model = get_orchestrator_model()
        agent = create_react_agent(model=model, tools=tools)
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=PROCESS_PROMPT.format(
                domain=domain, standup_id=standup_id,
                summarize=route["summarize"], deliver=route["deliver"],
            ))]},
            config={
                "recursion_limit": 6,
                "run_name": f"process_meeting:{standup_id}",
                "tags": ["orchestrator", "tier1-react", f"domain:{domain}"],
                "metadata": {"standup_id": standup_id, "domain": domain},
            },
        )

        # A completed ReAct loop only means the LLM finished reasoning — not that
        # the skills succeeded. Tool failures come back as {"status":"failed"}
        # JSON inside ToolMessages, not as exceptions, so inspect them.
        failures = _extract_tool_failures(result.get("messages", []))
        if failures:
            logger.warning(
                "process_meeting (ReAct) completed with skill failures",
                extra={"standup_id": standup_id, "domain": domain, "failures": failures},
            )
            return {"status": "failed", "step": "react", "error": "; ".join(failures)}

        logger.info("process_meeting (ReAct) complete", extra={"standup_id": standup_id, "domain": domain})
        return {"status": "completed", "messages": len(result.get("messages", []))}

    except Exception as e:
        logger.error(
            f"ReAct process_meeting failed, falling back to deterministic: {e}",
            exc_info=True,
            extra={"standup_id": standup_id, "domain": domain},
        )
        return await _run_deterministic(standup_id, domain)


# Backwards-compatible alias (standup domain).
async def process_standup(standup_id: str) -> dict:
    return await process_meeting(standup_id, domain="standup")
