"""
Manager Agent — A2A v0.3.0 compliant service (role-parameterized).

One codebase serves two roles, selected by settings.agent_role (AGENT_ROLE):
  - "standup" → Standup Manager Agent (summarize_standup, deliver_report, summarize_period)
  - "project" → Project Manager Agent (summarize_project, deliver_project_report, summarize_period)

Skills are dispatched via a per-role registry (agent.skills.registry) rather
than a hardcoded if/elif. All skills use MCP tools on the standup-tools server
for deterministic I/O; this server owns no LLM reasoning beyond the skills.

Endpoints (A2A v0.3.0):
  GET  /.well-known/agent-card.json   — Agent Card discovery
  POST /a2a                           — JSON-RPC 2.0 dispatcher (message/send, tasks/get, tasks/cancel)
  GET  /health                        — Health check

Launch (per role, same image):
    AGENT_ROLE=standup uvicorn agent.server:app --host 0.0.0.0 --port 8020
    AGENT_ROLE=project uvicorn agent.server:app --host 0.0.0.0 --port 8021
"""
import sys
import os

# Ensure project root is on path when running as a subprocess.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import uuid as _uuid

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from shared.config import settings
from shared.logging import setup_logging

from a2a.a2a_models import (
    JSONRPCRequest, JSONRPCResponse, JSONRPCError,
    MessageSendParams, Message, TextPart, DataPart,
    Task, TaskStatus, TaskState, Artifact,
)
from a2a.agent_cards import build_agent_card

from agent.skills.registry import get_registry

setup_logging()
logger = logging.getLogger(__name__)

AGENT_ROLE = settings.agent_role
AGENT_CARD = build_agent_card(AGENT_ROLE)
SKILL_REGISTRY = get_registry(AGENT_ROLE)

app = FastAPI(title=AGENT_CARD.name, version="1.0.0")

# In-memory task store (for tasks/get) — single-instance only, sufficient for
# this synchronous request/response pattern. A multi-instance deployment would
# use Redis or similar (documented as a Phase 2 item, unchanged from before).
_task_store: dict[str, dict] = {}


# ─── Extract skill data from A2A Message parts ──────────────────

def _extract_skill_data(message: Message) -> dict:
    """
    Extract skill-specific fields from the A2A Message parts.

    Supports:
      - DataPart with kind="data" → merge data dict
      - TextPart with kind="text" → ignored (this agent takes no free-text input)
    """
    skill_data: dict = {}
    for part in message.parts:
        if isinstance(part, dict):
            kind = part.get("kind", "")
            if kind == "data":
                skill_data.update(part.get("data", {}))
        elif isinstance(part, DataPart):
            skill_data.update(part.data)
    return skill_data


# ═══════════════════════════════════════════════════════════════════
# A2A v0.3.0 Endpoints
# ═══════════════════════════════════════════════════════════════════

@app.get("/.well-known/agent-card.json")
async def agent_card():
    """
    A2A v0.3.0 Agent Card discovery endpoint.

    Skills include inputSchema (JSON Schema) for client auto-discovery.
    Populates supportedInterfaces URL at runtime.
    """
    card_data = AGENT_CARD.model_dump()
    if card_data.get("supportedInterfaces"):
        base_url = f"{settings.a2a_scheme}://{settings.agent_host}:{settings.agent_port}"
        card_data["supportedInterfaces"][0]["url"] = f"{base_url}/a2a"
    return card_data


@app.get("/.well-known/agent.json")
async def agent_card_legacy():
    """Redirect old URL to spec-compliant URL."""
    return RedirectResponse("/.well-known/agent-card.json")


@app.get("/health")
async def health():
    return {"status": "ok", "agent": AGENT_CARD.name, "role": AGENT_ROLE, "protocolVersion": "0.3.0"}


@app.post("/a2a")
async def jsonrpc_dispatcher(request: Request) -> dict:
    """
    A2A v0.3.0 JSON-RPC 2.0 dispatcher.

    Handles:
      - message/send  — execute a skill synchronously
      - tasks/get     — retrieve task by ID
      - tasks/cancel  — cancel a task (returns current state)
    """
    try:
        body = await request.json()
    except Exception:
        return JSONRPCResponse(
            id="unknown",
            error=JSONRPCError(code=-32700, message="Parse error: invalid JSON"),
        ).model_dump(exclude_none=True)

    if body.get("jsonrpc") != "2.0" or "method" not in body:
        return JSONRPCResponse(
            id=body.get("id", "unknown"),
            error=JSONRPCError(code=-32600, message="Invalid Request: missing jsonrpc or method"),
        ).model_dump(exclude_none=True)

    rpc_id = body.get("id", "unknown")
    method = body["method"]
    params = body.get("params", {})

    if method == "message/send":
        return await _handle_message_send(rpc_id, params)
    elif method == "tasks/get":
        return _handle_tasks_get(rpc_id, params)
    elif method == "tasks/cancel":
        return _handle_tasks_cancel(rpc_id, params)
    else:
        return JSONRPCResponse(
            id=rpc_id,
            error=JSONRPCError(code=-32601, message=f"Method not found: {method}"),
        ).model_dump(exclude_none=True)


# ─── message/send handler ───────────────────────────────────────

async def _handle_message_send(rpc_id: str, params: dict) -> dict:
    """
    Handle message/send — the primary A2A method.

    Flow:
      1. Parse MessageSendParams (contains Message with parts)
      2. Extract skill-specific data from DataPart
      3. Create Task in SUBMITTED state, transition to WORKING
      4. Route to the skill handler (summarize_standup | deliver_report)
      5. Pack results into an Artifact with a DataPart
      6. Transition to COMPLETED (or FAILED)
      7. Return JSON-RPC response wrapping the Task
    """
    try:
        send_params = MessageSendParams(**params)
    except Exception as e:
        return JSONRPCResponse(
            id=rpc_id,
            error=JSONRPCError(code=-32602, message=f"Invalid params: {e}"),
        ).model_dump(exclude_none=True)

    user_msg = send_params.message
    skill_data = _extract_skill_data(user_msg)
    skill_id = skill_data.pop("_skill", "")

    logger.info(f"A2A message/send: role={AGENT_ROLE}, skill={skill_id}")

    task = Task(
        contextId=user_msg.contextId or str(_uuid.uuid4()),
        status=TaskStatus(state=TaskState.SUBMITTED),
        history=[user_msg],
        metadata=send_params.metadata,
    )
    task.status = TaskStatus(state=TaskState.WORKING)

    handler = SKILL_REGISTRY.get(skill_id)
    if handler is None:
        task.status = TaskStatus(
            state=TaskState.FAILED,
            message=Message(role="agent", parts=[TextPart(
                text=f"Unknown skill {skill_id!r} for role {AGENT_ROLE!r}")]),
        )
        _task_store[task.id] = task.model_dump()
        return JSONRPCResponse(id=rpc_id, result=task.model_dump()).model_dump(exclude_none=True)

    try:
        # Per-skill required-field validation lives in the registry handlers.
        result = await handler(skill_data)

        if result.get("status") == "failed":
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(role="agent", parts=[TextPart(text=result.get("error", "Skill failed"))]),
            )
        else:
            task.status = TaskStatus(state=TaskState.COMPLETED)
            task.artifacts = [Artifact(
                name=skill_id,
                description=f"Result of {skill_id}",
                parts=[DataPart(data=result)],
            )]

    except Exception as e:
        logger.error(f"Skill execution error: {e}", exc_info=True)
        task.status = TaskStatus(
            state=TaskState.FAILED,
            message=Message(role="agent", parts=[TextPart(text=str(e))]),
        )

    _task_store[task.id] = task.model_dump()
    return JSONRPCResponse(id=rpc_id, result=task.model_dump()).model_dump(exclude_none=True)


# ─── tasks/get handler ──────────────────────────────────────────

def _handle_tasks_get(rpc_id: str, params: dict) -> dict:
    task_id = params.get("id", "")
    if not task_id:
        return JSONRPCResponse(
            id=rpc_id,
            error=JSONRPCError(code=-32602, message="Invalid params: 'id' is required"),
        ).model_dump(exclude_none=True)

    task_data = _task_store.get(task_id)
    if not task_data:
        return JSONRPCResponse(
            id=rpc_id,
            error=JSONRPCError(code=-32001, message=f"Task not found: {task_id}"),
        ).model_dump(exclude_none=True)

    return JSONRPCResponse(id=rpc_id, result=task_data).model_dump(exclude_none=True)


# ─── tasks/cancel handler ───────────────────────────────────────

def _handle_tasks_cancel(rpc_id: str, params: dict) -> dict:
    task_id = params.get("id", "")
    task_data = _task_store.get(task_id)
    if not task_data:
        return JSONRPCResponse(
            id=rpc_id,
            error=JSONRPCError(code=-32001, message=f"Task not found: {task_id}"),
        ).model_dump(exclude_none=True)

    current_state = task_data.get("status", {}).get("state", "")
    if current_state in ("completed", "failed", "canceled"):
        return JSONRPCResponse(id=rpc_id, result=task_data).model_dump(exclude_none=True)

    task_data["status"] = TaskStatus(state=TaskState.CANCELED).model_dump()
    _task_store[task_id] = task_data
    return JSONRPCResponse(id=rpc_id, result=task_data).model_dump(exclude_none=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.agent_port)
