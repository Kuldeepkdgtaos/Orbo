from datetime import date, datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

Domain = Literal["standup", "project"]


# ── Participant schemas ──────────────────────────────────────────────────────

class ParticipantCreate(BaseModel):
    name: str
    email: str
    teams_display_name: str
    order_index: int
    designation: Optional[str] = None
    department: Optional[str] = None
    is_manager: bool = False


class ParticipantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    standup_id: str
    name: str
    email: str
    teams_display_name: str
    order_index: int
    designation: Optional[str] = None
    department: Optional[str] = None
    is_manager: bool = False


# ── Template schemas ─────────────────────────────────────────────────────────

class TemplateParticipantCreate(BaseModel):
    name: str
    email: str
    teams_display_name: str
    order_index: int
    designation: Optional[str] = None
    department: Optional[str] = None
    is_manager: bool = False


class TemplateParticipantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    template_id: str
    name: str
    email: str
    teams_display_name: str
    order_index: int
    designation: Optional[str] = None
    department: Optional[str] = None
    is_manager: bool = False


class TemplateCreate(BaseModel):
    name: str
    team_name: str
    meeting_url: str
    domain: Domain = "standup"
    management_recipients: list[str] = []
    participants: list[TemplateParticipantCreate]


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    team_name: str
    meeting_url: str
    domain: str = "standup"
    management_recipients: list[str]
    created_at: datetime
    updated_at: datetime
    participants: list[TemplateParticipantRead] = []


class TemplateListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    team_name: str
    domain: str = "standup"
    created_at: datetime
    participant_count: int = 0
    session_count: int = 0


# ── Standup schemas ──────────────────────────────────────────────────────────

class StandupCreate(BaseModel):
    name: str
    team_name: str
    meeting_url: str
    domain: Domain = "standup"
    scheduled_at: Optional[datetime] = None
    management_recipients: list[str] = []
    participants: list[ParticipantCreate]


class StandupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    team_name: str
    meeting_url: str
    domain: str = "standup"
    status: str
    scheduled_at: Optional[datetime]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    recall_bot_id: Optional[str]
    management_recipients: list[str]
    template_id: Optional[str] = None
    session_number: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    participants: list[ParticipantRead] = []


class StandupListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    team_name: str
    domain: str = "standup"
    status: str
    scheduled_at: Optional[datetime]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    created_at: datetime
    participant_count: int = 0
    template_id: Optional[str] = None
    session_number: Optional[int] = None


# ── Other schemas (unchanged) ────────────────────────────────────────────────

class StateTransitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    standup_id: str
    from_state: Optional[str]
    to_state: str
    event: str
    occurred_at: datetime


class UtteranceIngest(BaseModel):
    standup_id: str
    speaker_label: str
    text: str
    started_at: datetime
    ended_at: datetime
    confidence: Optional[float] = None


class UtteranceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    standup_id: str
    participant_id: Optional[str]
    speaker_label: str
    text: str
    started_at: datetime
    ended_at: datetime
    confidence: Optional[float]
    created_at: datetime


class ParticipantSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    standup_id: str
    participant_id: str
    yesterday: str
    today: str
    blockers: str
    model: str
    prompt_version: str
    created_at: datetime


class StandupSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    standup_id: str
    rollup_markdown: str
    key_blockers: list[Any]
    key_wins: list[Any]
    model: str
    prompt_version: str
    created_at: datetime


class EmailDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    standup_id: str
    recipients: list[Any]
    subject: str
    body_preview: str
    graph_message_id: Optional[str]
    status: str
    error: Optional[str]
    sent_at: datetime


class RecallWebhookPayload(BaseModel):
    event: str
    data: dict[str, Any]


# ── Auth schemas (multi-user) ────────────────────────────────────────────────

class UserRegister(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: str
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    dataentry_schema: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


# ── Aggregate / historic summary schemas ─────────────────────────────────────

Scope = Literal["call", "individual", "project", "overall"]
Granularity = Literal["overall", "weekly", "monthly"]


class AggregateRequest(BaseModel):
    domain: Domain
    scope: Scope
    granularity: Granularity = "overall"
    range_start: date
    range_end: date
    subject_id: Optional[str] = None            # participant_id / template_id; None → global
    dataentry_table_ids: list[str] = []         # optional Data Entry tables to fold into context
    force: bool = False                          # bypass cache and regenerate


class AggregateSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    domain: str
    scope: str
    granularity: str
    range_start: date
    range_end: date
    subject_type: str
    subject_id: Optional[str] = None
    bucket_key: str
    rollup_markdown: str
    key_points: list[Any]
    data_entry_refs: list[Any]
    model: str
    prompt_version: str
    created_at: datetime
    updated_at: datetime


# ── Data Entry schemas (per-user dynamic tables) ─────────────────────────────

DataEntryColumnType = Literal["text", "number", "boolean", "date", "timestamp"]


class DataEntryColumnDef(BaseModel):
    display_name: str
    data_type: DataEntryColumnType = "text"


class DataEntryTableCreate(BaseModel):
    display_name: str
    domain: Domain = "standup"
    columns: list[DataEntryColumnDef] = []


class DataEntryTableRename(BaseModel):
    display_name: str


class DataEntryColumnRead(BaseModel):
    id: str
    physical_name: str
    display_name: str
    data_type: str
    order_index: int


class DataEntryTableRead(BaseModel):
    id: str
    physical_name: str
    display_name: str
    domain: str
    created_at: datetime
    columns: list[DataEntryColumnRead] = []


class DataEntryColumnAdd(BaseModel):
    display_name: str
    data_type: DataEntryColumnType = "text"


class DataEntryRowWrite(BaseModel):
    # Keyed by column physical_name → value (JSON scalar).
    values: dict[str, Any]
