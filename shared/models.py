import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


# Meeting/summary domains. A standup and a project meeting share the same
# Recall pipeline and tables — they differ only by this discriminator and the
# summary lens applied to them.
DOMAIN_STANDUP = "standup"
DOMAIN_PROJECT = "project"


def gen_uuid():
    return str(uuid.uuid4())


class StandupTemplate(Base):
    __tablename__ = "standup_templates"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    team_name: Mapped[str] = mapped_column(Text, nullable=False)
    meeting_url: Mapped[str] = mapped_column(Text, nullable=False)
    management_recipients: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # 'standup' | 'project' — which management domain this template belongs to.
    domain: Mapped[str] = mapped_column(Text, nullable=False, default=DOMAIN_STANDUP, server_default=DOMAIN_STANDUP)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    participants: Mapped[list["TemplateParticipant"]] = relationship(
        "TemplateParticipant", back_populates="template", cascade="all, delete-orphan",
        order_by="TemplateParticipant.order_index",
    )
    sessions: Mapped[list["Standup"]] = relationship(
        "Standup", back_populates="template", foreign_keys="Standup.template_id",
    )


class TemplateParticipant(Base):
    __tablename__ = "template_participants"
    __table_args__ = (UniqueConstraint("template_id", "order_index", name="uq_template_participants_order"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    template_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("standup_templates.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    teams_display_name: Mapped[str] = mapped_column(Text, nullable=False)
    designation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    department: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_manager: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    template: Mapped["StandupTemplate"] = relationship("StandupTemplate", back_populates="participants")


class Standup(Base):
    __tablename__ = "standups"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    team_name: Mapped[str] = mapped_column(Text, nullable=False)
    meeting_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="idle")
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    recall_bot_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    management_recipients: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # 'standup' | 'project' — which management domain this meeting belongs to.
    # Drives which agent summarizes it and where it appears in the UI.
    domain: Mapped[str] = mapped_column(Text, nullable=False, default=DOMAIN_STANDUP, server_default=DOMAIN_STANDUP)
    # Template linkage — NULL for standalone standups (backwards compatible)
    template_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("standup_templates.id", ondelete="SET NULL"), nullable=True,
    )
    session_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    template: Mapped[Optional["StandupTemplate"]] = relationship(
        "StandupTemplate", back_populates="sessions", foreign_keys=[template_id],
    )
    participants: Mapped[list["Participant"]] = relationship("Participant", back_populates="standup", cascade="all, delete-orphan", order_by="Participant.order_index")
    state_transitions: Mapped[list["StateTransition"]] = relationship("StateTransition", back_populates="standup", cascade="all, delete-orphan")
    utterances: Mapped[list["Utterance"]] = relationship("Utterance", back_populates="standup", cascade="all, delete-orphan")
    participant_summaries: Mapped[list["ParticipantSummary"]] = relationship("ParticipantSummary", back_populates="standup", cascade="all, delete-orphan")
    standup_summary: Mapped[Optional["StandupSummary"]] = relationship("StandupSummary", back_populates="standup", cascade="all, delete-orphan", uselist=False)
    email_deliveries: Mapped[list["EmailDelivery"]] = relationship("EmailDelivery", back_populates="standup", cascade="all, delete-orphan")


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("standup_id", "order_index"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    standup_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("standups.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    teams_display_name: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    designation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    department: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_manager: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    standup: Mapped["Standup"] = relationship("Standup", back_populates="participants")
    utterances: Mapped[list["Utterance"]] = relationship("Utterance", back_populates="participant")
    summary: Mapped[Optional["ParticipantSummary"]] = relationship("ParticipantSummary", back_populates="participant", uselist=False)


class StateTransition(Base):
    __tablename__ = "state_transitions"
    __table_args__ = (Index("idx_state_transitions_standup", "standup_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    standup_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("standups.id", ondelete="CASCADE"), nullable=False)
    from_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    to_state: Mapped[str] = mapped_column(Text, nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    standup: Mapped["Standup"] = relationship("Standup", back_populates="state_transitions")


class Utterance(Base):
    __tablename__ = "utterances"
    __table_args__ = (Index("idx_utterances_standup", "standup_id", "started_at"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    standup_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("standups.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("participants.id", ondelete="SET NULL"), nullable=True)
    speaker_label: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    standup: Mapped["Standup"] = relationship("Standup", back_populates="utterances")
    participant: Mapped[Optional["Participant"]] = relationship("Participant", back_populates="utterances")


class ParticipantSummary(Base):
    __tablename__ = "participant_summaries"
    __table_args__ = (UniqueConstraint("standup_id", "participant_id"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    standup_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("standups.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("participants.id", ondelete="CASCADE"), nullable=False)
    yesterday: Mapped[str] = mapped_column(Text, nullable=False, default="")
    today: Mapped[str] = mapped_column(Text, nullable=False, default="")
    blockers: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_response: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    standup: Mapped["Standup"] = relationship("Standup", back_populates="participant_summaries")
    participant: Mapped["Participant"] = relationship("Participant", back_populates="summary")


class StandupSummary(Base):
    __tablename__ = "standup_summaries"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    standup_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("standups.id", ondelete="CASCADE"), nullable=False, unique=True)
    rollup_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    key_blockers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    key_wins: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    standup: Mapped["Standup"] = relationship("Standup", back_populates="standup_summary")


class EmailDelivery(Base):
    __tablename__ = "email_deliveries"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    standup_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("standups.id", ondelete="CASCADE"), nullable=False)
    recipients: Mapped[list] = mapped_column(JSONB, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body_preview: Mapped[str] = mapped_column(Text, nullable=False)
    graph_message_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    standup: Mapped["Standup"] = relationship("Standup", back_populates="email_deliveries")


class User(Base):
    """Application user (multi-user auth).

    Only the per-user Data Entry schema is isolated by user — meetings,
    standups, templates and summaries remain shared across all users. This
    row exists to gate access (JWT auth) and to own a dedicated Postgres
    schema (``dataentry_schema``) that holds the user's dynamic tables.
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # stored lowercased
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Dedicated Postgres schema holding this user's Data Entry tables.
    dataentry_schema: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AggregateSummary(Base):
    """Cache of historic / aggregated GPT-4o summaries.

    Unlike ``standup_summaries`` (exactly one row per standup), this table
    holds cross-meeting rollups over a date range at a chosen granularity.
    Generated on-demand and reused until a caller forces regeneration.

    The unique tuple ``(domain, scope, granularity, range_start, range_end,
    subject_id, bucket_key)`` is the cache key. ``subject_id`` is NULL for
    global/team-wide rollups (participant_id for individual scope, template_id
    for a project series). ``bucket_key`` distinguishes buckets within a
    granularity, e.g. 'overall', '2026-07' (monthly), '2026-W28' (weekly).
    """
    __tablename__ = "aggregate_summaries"
    __table_args__ = (
        UniqueConstraint(
            "domain", "scope", "granularity", "range_start", "range_end",
            "subject_id", "bucket_key", name="uq_aggregate_summaries_key",
        ),
        Index("idx_aggregate_summaries_lookup", "domain", "scope", "granularity", "range_start", "range_end"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    domain: Mapped[str] = mapped_column(Text, nullable=False)              # standup | project
    scope: Mapped[str] = mapped_column(Text, nullable=False)              # call | individual | project | overall
    granularity: Mapped[str] = mapped_column(Text, nullable=False)        # overall | weekly | monthly
    range_start: Mapped[date] = mapped_column(Date, nullable=False)
    range_end: Mapped[date] = mapped_column(Date, nullable=False)
    subject_type: Mapped[str] = mapped_column(Text, nullable=False, default="global")  # global | team | participant | template
    # Empty string (NOT NULL) for global/team scopes — Postgres unique
    # constraints treat NULLs as distinct, which would defeat cache dedup, so
    # "no subject" is the sentinel '' rather than NULL. participant_id for
    # individual scope, template_id for a project series.
    subject_id: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    bucket_key: Mapped[str] = mapped_column(Text, nullable=False, default="overall")
    rollup_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    data_entry_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
