"""
A2A v0.3.0 Agent Registry — discovers the Standup Manager Agent via its
Agent Card and exposes its skills as LangChain tools for the orchestrator's
Tier-1 ReAct agent.

True auto-discovery: fetches the live Agent Card from the agent's
/.well-known/agent-card.json endpoint, reads skill.inputSchema (JSON Schema),
and dynamically builds Pydantic models for StructuredTool.args_schema.

The orchestrator never imports agent-internal code — it only knows:
  - the agent's URL (from settings)
  - the A2A protocol (JSON-RPC 2.0)
  - the Agent Card schema (skills[].inputSchema)

New skills are picked up automatically when the agent's card changes — no
orchestrator code changes needed.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field as PydanticField, create_model
from langchain_core.tools import StructuredTool

from shared.config import settings
from a2a.a2a_client import A2AClient

logger = logging.getLogger(__name__)


# ─── JSON Schema → Pydantic dynamic model builder ───────────────

_JSON_TYPE_MAP: Dict[str, type] = {
    "string":  str,
    "integer": int,
    "number":  float,
    "boolean": bool,
    "object":  dict,
    "array":   list,
}


def _build_args_schema(skill_id: str, input_schema: dict) -> type[BaseModel]:
    """Build a dynamic Pydantic model from a JSON Schema dict (skill.inputSchema)."""
    properties = input_schema.get("properties", {})
    required_fields = set(input_schema.get("required", []))

    field_definitions: Dict[str, Any] = {}
    for field_name, field_spec in properties.items():
        base_type = _JSON_TYPE_MAP.get(field_spec.get("type", "string"), Any)
        description = field_spec.get("description", "")
        is_required = field_name in required_fields

        if is_required:
            field_definitions[field_name] = (base_type, PydanticField(description=description))
        else:
            default = field_spec.get("default")
            field_definitions[field_name] = (
                Optional[base_type] if default is None else base_type,
                PydanticField(default=default, description=description),
            )

    model_name = f"{skill_id}_Input"
    return create_model(model_name, **field_definitions)


# ─── Registry ───────────────────────────────────────────────────

class A2AAgentRegistry:
    """
    Registry of A2A agents — discovers availability via Agent Cards and
    converts skills into LangChain StructuredTool objects.
    """

    def __init__(self):
        self._agents: dict[str, dict] = {}   # {name: {"client": A2AClient}}
        self._setup_from_settings()

    def _setup_from_settings(self):
        if settings.standup_agent_enabled:
            url = f"{settings.a2a_scheme}://{settings.standup_agent_host}:{settings.standup_agent_port}"
            self._agents["standup_agent"] = {"client": A2AClient(url)}
            logger.info(f"Standup Manager Agent registered: {url}")

        if settings.project_agent_enabled:
            url = f"{settings.a2a_scheme}://{settings.project_agent_host}:{settings.project_agent_port}"
            self._agents["project_agent"] = {"client": A2AClient(url)}
            logger.info(f"Project Manager Agent registered: {url}")

        if not self._agents:
            logger.info("No A2A agents enabled")

    def get_client(self, agent_name: str) -> Optional[A2AClient]:
        """Direct client access — used by the deterministic fallback path and
        by routes that call a skill without going through the ReAct agent."""
        entry = self._agents.get(agent_name)
        return entry["client"] if entry else None

    async def get_tools(self, agent_name: Optional[str] = None) -> list[StructuredTool]:
        """
        Discover available A2A agents and return their skills as LangChain tools.

        Pass ``agent_name`` to restrict discovery to a single agent — this keeps
        the ReAct tool list free of cross-agent skill-id collisions (both agents
        expose ``summarize_period``) and scopes post-meeting processing to the
        right agent for the meeting's domain.
        """
        tools: List[StructuredTool] = []
        agents = (
            {agent_name: self._agents[agent_name]}
            if agent_name and agent_name in self._agents
            else self._agents
        )
        for agent_name, entry in agents.items():
            client: A2AClient = entry["client"]
            try:
                card = await client.get_agent_card()
                for skill in card.skills:
                    args_schema = None
                    if skill.inputSchema:
                        args_schema = _build_args_schema(skill.id, skill.inputSchema)
                    else:
                        logger.warning(
                            f"A2A skill '{skill.id}' has no inputSchema — "
                            f"StructuredTool will accept any kwargs"
                        )
                    tool = self._skill_to_tool(client, skill, args_schema, agent_name)
                    tools.append(tool)
                    logger.info(f"A2A skill discovered: {skill.id} (from {card.name})")
            except Exception as e:
                logger.warning(f"A2A discovery failed for {agent_name}: {e}")
        return tools

    def _skill_to_tool(
        self, client: A2AClient, skill, args_schema: type[BaseModel] | None,
        agent_name: str,
    ) -> StructuredTool:
        """
        Convert an A2A agent skill into a LangChain StructuredTool.

        The tool wrapper packs kwargs into a DataPart, sends via A2A
        message/send, and extracts the DataPart from the first artifact
        as a JSON string for the LLM to consume.
        """
        skill_id = skill.id  # capture for closure

        async def invoke_skill(**kwargs) -> str:
            task = await client.send_task(skill_data={**kwargs, "_skill": skill_id})

            task_state = task.status.state
            state_value = task_state if isinstance(task_state, str) else task_state.value

            if state_value == "failed":
                error_msg = "Standup Manager Agent task failed"
                if task.status.message and task.status.message.parts:
                    for part in task.status.message.parts:
                        p = part if isinstance(part, dict) else part.model_dump()
                        if p.get("kind") == "text":
                            error_msg = p.get("text", error_msg)
                            break
                return json.dumps({"status": "failed", "error": error_msg}, default=str)

            for artifact in task.artifacts:
                art = artifact if isinstance(artifact, dict) else artifact.model_dump()
                for part in art.get("parts", []):
                    if part.get("kind") == "data":
                        return json.dumps(part.get("data", {}), default=str)

            return json.dumps({"status": "completed"}, default=str)

        return StructuredTool(
            name=skill.id,
            description=skill.description,
            args_schema=args_schema,
            coroutine=invoke_skill,
            tags=["a2a", f"agent:{agent_name}"],
            metadata={"a2a_agent": agent_name},
        )


# Module-level singleton
agent_registry = A2AAgentRegistry()
