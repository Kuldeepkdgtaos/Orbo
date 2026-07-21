import asyncio
import logging
from enum import Enum
from typing import Any, Optional, TypedDict

logger = logging.getLogger(__name__)


class StandupStateEnum(str, Enum):
    IDLE = "idle"
    BOT_DISPATCHED = "bot_dispatched"
    BOT_JOINED = "bot_joined"
    WAITING_FOR_QUORUM = "waiting_for_quorum"
    GREETING = "greeting"
    ASKING = "asking"
    LISTENING = "listening"
    NEXT_PERSON = "next_person"
    WRAP_UP = "wrap_up"
    COMPLETED = "completed"
    FAILED = "failed"


class StandupGraphState(TypedDict):
    standup_id: str
    current_state: str
    current_participant_index: int
    participants: list[dict[str, Any]]
    recall_bot_id: Optional[str]
    error: Optional[str]
    last_utterance_at: Optional[float]


def create_initial_state(standup_id: str, participants: list[dict], recall_bot_id: Optional[str] = None) -> StandupGraphState:
    return StandupGraphState(
        standup_id=standup_id,
        current_state=StandupStateEnum.IDLE,
        current_participant_index=0,
        participants=participants,
        recall_bot_id=recall_bot_id,
        error=None,
        last_utterance_at=None,
    )


# In-memory state store — Phase 1 stub. Replace with Redis in Phase 2 for multi-instance support.
_state_store: dict[str, StandupGraphState] = {}


def get_state(standup_id: str) -> Optional[StandupGraphState]:
    return _state_store.get(standup_id)


def set_state(standup_id: str, state: StandupGraphState) -> None:
    _state_store[standup_id] = state


def transition_state(standup_id: str, new_state: str, **kwargs) -> StandupGraphState:
    current = _state_store.get(standup_id, {})
    updated = {**current, "current_state": new_state, **kwargs}
    _state_store[standup_id] = updated
    logger.info("state_transition", extra={"standup_id": standup_id, "new_state": new_state})
    return updated
