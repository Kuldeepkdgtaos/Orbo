"""
A2A v0.3.0 Protocol Models — shared by client and server.

Based on Google's A2A specification (a2a.proto):
  https://github.com/google/A2A
  https://a2a-protocol.org/v0.3.0/specification/

These Pydantic models mirror the protobuf definitions for the JSON-RPC
transport binding used between the orchestrator (A2A client) and the
Standup Manager Agent (A2A server).
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# ─── Helpers ─────────────────────────────────────────────────────

def _new_id() -> str:
    return str(_uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Task State Machine (a2a.proto: TaskState) ──────────────────

class TaskState(str, Enum):
    """
    Lifecycle states for an A2A Task.

    Terminal states: COMPLETED, FAILED, CANCELED
    """
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    INPUT_REQUIRED = "input-required"
    AUTH_REQUIRED = "auth-required"
    REJECTED = "rejected"


# ─── Parts (a2a.proto: Part — discriminated by 'kind') ──────────

class TextPart(BaseModel):
    """Plain-text message content."""
    kind: str = "text"
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DataPart(BaseModel):
    """Structured JSON data content."""
    kind: str = "data"
    data: Dict[str, Any]
    mimeType: str = "application/json"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FilePart(BaseModel):
    """Binary file or URI reference."""
    kind: str = "file"
    mimeType: str = ""
    data: str = ""          # base64-encoded bytes
    uri: str = ""           # HTTPS URL
    filename: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


# Union type for message/artifact parts
Part = Union[TextPart, DataPart, FilePart]


# ─── Message (a2a.proto: Message) ───────────────────────────────

class Message(BaseModel):
    """
    A single message exchanged between client (user) and agent.

    role: "user" (client → agent) or "agent" (agent → client)
    parts: ordered list of content parts (text, data, file)
    """
    messageId: str = Field(default_factory=_new_id)
    role: str                               # "user" | "agent"
    parts: List[Part]
    taskId: Optional[str] = None
    contextId: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    extensions: List[str] = Field(default_factory=list)
    referenceTaskIds: List[str] = Field(default_factory=list)


# ─── Artifact (a2a.proto: Artifact) ─────────────────────────────

class Artifact(BaseModel):
    """
    An output produced by a task — e.g., summary results, delivery status.

    artifactId must be unique within a Task.
    """
    artifactId: str = Field(default_factory=_new_id)
    name: str = ""
    description: str = ""
    parts: List[Part] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    extensions: List[str] = Field(default_factory=list)


# ─── Task (a2a.proto: Task) ─────────────────────────────────────

class TaskStatus(BaseModel):
    """Current status of a Task including state, optional message, and timestamp."""
    model_config = {"use_enum_values": True}

    state: TaskState
    message: Optional[Message] = None
    timestamp: str = Field(default_factory=_now_iso)


class Task(BaseModel):
    """
    The core unit of work in A2A — tracks lifecycle, messages, and outputs.

    State machine: submitted → working → completed | failed | canceled
                   working → input-required → working (after user reply)
    """
    id: str = Field(default_factory=_new_id)
    contextId: str = Field(default_factory=_new_id)
    status: TaskStatus
    artifacts: List[Artifact] = Field(default_factory=list)
    history: List[Message] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    kind: str = "task"


# ─── JSON-RPC 2.0 Envelope (spec §3) ────────────────────────────

class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 request envelope."""
    jsonrpc: str = "2.0"
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)
    id: str = Field(default_factory=_new_id)


class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 error object."""
    code: int
    message: str
    data: Any = None


class JSONRPCResponse(BaseModel):
    """JSON-RPC 2.0 response envelope — either result or error, never both."""
    jsonrpc: str = "2.0"
    result: Any = None
    error: Optional[JSONRPCError] = None
    id: str


# ─── message/send Params (a2a.proto: SendMessageRequest) ────────

class SendMessageConfiguration(BaseModel):
    """Configuration for a message/send request."""
    acceptedOutputModes: List[str] = Field(default_factory=lambda: ["application/json"])
    historyLength: Optional[int] = None
    returnImmediately: bool = False


class MessageSendParams(BaseModel):
    """Parameters for the message/send JSON-RPC method."""
    message: Message
    configuration: Optional[SendMessageConfiguration] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Streaming Events (a2a.proto: StreamResponse) ───────────────
# Not used in this iteration (agent cards declare streaming=False) — kept for
# protocol completeness / future use.

class TaskStatusUpdateEvent(BaseModel):
    """SSE event: task status changed."""
    type: str = "task-status-update"
    taskId: str
    contextId: str
    status: TaskStatus
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskArtifactUpdateEvent(BaseModel):
    """SSE event: new or updated artifact."""
    type: str = "task-artifact-update"
    taskId: str
    contextId: str
    artifact: Artifact
    append: bool = False
    lastChunk: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Agent Card & Skills (a2a.proto: AgentCard) ─────────────────

class AgentSkill(BaseModel):
    """A capability exposed by an A2A agent."""
    id: str                                     # unique skill identifier
    name: str                                   # human-readable name
    description: str                            # detailed description
    tags: List[str] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    inputModes: List[str] = Field(default_factory=lambda: ["application/json"])
    outputModes: List[str] = Field(default_factory=lambda: ["application/json"])
    # JSON Schema describing the skill's input parameters.
    # Serialized in the Agent Card JSON — clients use it to build typed tool schemas.
    inputSchema: Optional[Dict[str, Any]] = None


class AgentCapabilities(BaseModel):
    """Declares what optional features the agent supports."""
    streaming: bool = False
    pushNotifications: bool = False
    stateTransitionHistory: bool = False
    extensions: List[Dict[str, Any]] = Field(default_factory=list)
    extendedAgentCard: bool = False


class AgentInterface(BaseModel):
    """A transport endpoint the agent supports."""
    url: str                                    # absolute URL to the A2A endpoint
    protocolBinding: str = "JSONRPC"            # "JSONRPC" | "GRPC" | "HTTP+JSON"
    protocolVersion: str = "0.3.0"
    tenant: str = ""


class AgentProvider(BaseModel):
    """Organization that hosts/operates the agent."""
    organization: str
    url: str = ""


class AgentCard(BaseModel):
    """
    Agent discovery manifest — served at /.well-known/agent-card.json

    Contains identity, capabilities, supported transports, and skill definitions.
    Clients use this to discover what the agent can do and how to communicate.
    """
    name: str
    description: str
    version: str = "1.0.0"
    protocolVersion: str = "0.3.0"
    supportedInterfaces: List[AgentInterface] = Field(default_factory=list)
    provider: Optional[AgentProvider] = None
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    defaultInputModes: List[str] = Field(default_factory=lambda: ["application/json"])
    defaultOutputModes: List[str] = Field(default_factory=lambda: ["application/json"])
    skills: List[AgentSkill] = Field(default_factory=list)
    documentationUrl: str = ""
    iconUrl: str = ""
