"""
Utterance ingestion — attributes a raw transcript line to a participant and
stages it for persistence.

Previously an HTTP call from meeting_orchestrator to transcription_service
(POST /utterances/ingest); now an in-process function since both concerns
live in the orchestrator. Caller is responsible for loading
`standup.participants` (selectinload) and committing the session.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Union

from shared.models import Standup, Utterance
from .attribution import attribute_speaker

logger = logging.getLogger(__name__)


def _coerce_timestamp(value: Union[str, datetime]) -> datetime:
    """
    Recall's transcript JSON gives timestamps as ISO-8601 strings (e.g.
    "2026-07-07T13:26:16.465Z"), not datetime objects. asyncpg requires an
    actual datetime for a TIMESTAMPTZ column — it will not coerce a string
    itself, unlike Pydantic (which used to do this for free when utterance
    ingestion went through an HTTP call validated by a Pydantic schema,
    before that hop was collapsed into this in-process call). Parse
    defensively here so every caller gets this for free.
    """
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse timestamp {value!r}, using now(): {e}")
        return datetime.now(timezone.utc)


def build_utterance(
    standup: Standup,
    speaker_label: str,
    text: str,
    started_at: Union[str, datetime],
    ended_at: Union[str, datetime],
    confidence: Optional[float] = None,
) -> Utterance:
    """Attribute a transcript line to a participant and build an Utterance row
    (not yet added to a session — caller adds + commits)."""
    participants_data = [{"id": p.id, "teams_display_name": p.teams_display_name} for p in standup.participants]
    participant_id, _is_fuzzy = attribute_speaker(speaker_label, participants_data)

    return Utterance(
        standup_id=standup.id,
        participant_id=participant_id,
        speaker_label=speaker_label,
        text=text,
        started_at=_coerce_timestamp(started_at),
        ended_at=_coerce_timestamp(ended_at),
        confidence=confidence,
    )
