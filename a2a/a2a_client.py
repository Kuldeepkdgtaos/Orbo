"""
A2A v0.3.0 Protocol HTTP client — used by the orchestrator to communicate
with the Standup Manager Agent via JSON-RPC 2.0.

Implements:
  - Agent Card discovery: GET /.well-known/agent-card.json
  - message/send:         POST /a2a  (JSON-RPC 2.0)
  - tasks/get:            POST /a2a  (JSON-RPC 2.0)

Usage:
    client = A2AClient("http://standup-agent:8020")
    card = await client.get_agent_card()
    task = await client.send_task({"_skill": "summarize_standup", "standup_id": "..."})
"""
import logging
import httpx

from a2a.a2a_models import (
    AgentCard, Task, Message, DataPart,
    JSONRPCRequest, MessageSendParams,
)

logger = logging.getLogger(__name__)


class A2AClient:
    """A2A v0.3.0 JSON-RPC client — discovers and calls the Standup Manager Agent."""

    def __init__(self, agent_url: str, timeout: float = 120.0):
        self.agent_url = agent_url.rstrip("/")
        self.timeout = timeout
        self._card: AgentCard | None = None

    # ─── Agent Card Discovery ────────────────────────────────────

    async def get_agent_card(self) -> AgentCard:
        """
        GET /.well-known/agent-card.json — discover agent capabilities.

        A2A v0.3.0 spec: agent-card.json (not agent.json).
        Follows redirects for backward compatibility.
        """
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(f"{self.agent_url}/.well-known/agent-card.json")
            resp.raise_for_status()
            self._card = AgentCard(**resp.json())
        return self._card

    # ─── message/send (JSON-RPC 2.0) ────────────────────────────

    async def send_message(self, message: Message, metadata: dict = None) -> Task:
        """
        Send a message/send JSON-RPC request and return the Task object.

        This is the primary A2A communication method. The agent receives
        the Message, processes it, and returns a Task with status and artifacts.
        """
        rpc_request = JSONRPCRequest(
            method="message/send",
            params=MessageSendParams(
                message=message,
                metadata=metadata or {},
            ).model_dump(),
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.agent_url}/a2a",
                json=rpc_request.model_dump(),
            )
            resp.raise_for_status()

        rpc_response = resp.json()

        # Check for JSON-RPC error
        if rpc_response.get("error"):
            error = rpc_response["error"]
            raise RuntimeError(
                f"A2A JSON-RPC error [{error.get('code')}]: {error.get('message')}"
            )

        # Parse the Task from the result
        return Task(**rpc_response["result"])

    # ─── Convenience: send skill data as DataPart ────────────────

    async def send_task(self, skill_data: dict) -> Task:
        """
        Convenience wrapper: pack skill-specific data into an A2A Message
        and send via message/send.

        This is the method called by A2AAgentRegistry's tool wrappers.
        The skill_data dict (standup_id, force_resend, _skill, etc.) is
        wrapped in a DataPart inside a user Message.
        """
        message = Message(
            role="user",
            parts=[DataPart(data=skill_data)],
        )
        return await self.send_message(message)

    # ─── tasks/get (JSON-RPC 2.0) ───────────────────────────────

    async def get_task(self, task_id: str) -> Task:
        """Retrieve a task by ID via tasks/get JSON-RPC method."""
        rpc_request = JSONRPCRequest(
            method="tasks/get",
            params={"id": task_id},
        )

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.agent_url}/a2a",
                json=rpc_request.model_dump(),
            )
            resp.raise_for_status()

        rpc_response = resp.json()
        if rpc_response.get("error"):
            error = rpc_response["error"]
            raise RuntimeError(
                f"A2A JSON-RPC error [{error.get('code')}]: {error.get('message')}"
            )

        return Task(**rpc_response["result"])

    # ─── Health Check ────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Quick check if the agent is reachable via Agent Card endpoint."""
        try:
            await self.get_agent_card()
            return True
        except Exception as e:
            logger.warning(f"A2A health check failed for {self.agent_url}: {e}")
            return False

    def __repr__(self) -> str:
        return f"A2AClient(url={self.agent_url})"
