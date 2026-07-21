import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from shared.db import get_db
from shared.models import Utterance
from shared.schemas import UtteranceRead

logger = logging.getLogger(__name__)
router = APIRouter(tags=["utterances"])


@router.get("/standups/{standup_id}/utterances", response_model=list[UtteranceRead])
async def get_utterances(standup_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Utterance).where(Utterance.standup_id == standup_id).order_by(Utterance.started_at)
    )
    return result.scalars().all()


@router.get("/standups/{standup_id}/participants/{participant_id}/utterances", response_model=list[UtteranceRead])
async def get_participant_utterances(standup_id: str, participant_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Utterance)
        .where(Utterance.standup_id == standup_id, Utterance.participant_id == participant_id)
        .order_by(Utterance.started_at)
    )
    return result.scalars().all()
