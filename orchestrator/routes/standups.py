import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from shared.db import get_db
from shared.models import Standup, Participant, StateTransition
from shared.schemas import StandupCreate, StandupRead, StandupListItem

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/standups", tags=["standups"])


@router.post("", response_model=StandupRead, status_code=201)
async def create_standup(payload: StandupCreate, db: AsyncSession = Depends(get_db)):
    standup = Standup(
        name=payload.name,
        team_name=payload.team_name,
        meeting_url=payload.meeting_url,
        domain=payload.domain,
        scheduled_at=payload.scheduled_at,
        management_recipients=payload.management_recipients,
        status="idle",
    )
    db.add(standup)
    await db.flush()

    for p in payload.participants:
        participant = Participant(
            standup_id=standup.id,
            name=p.name,
            email=p.email,
            teams_display_name=p.teams_display_name,
            order_index=p.order_index,
            designation=p.designation,
            department=p.department,
            is_manager=p.is_manager,
        )
        db.add(participant)

    transition = StateTransition(
        standup_id=standup.id,
        from_state=None,
        to_state="idle",
        event="created",
    )
    db.add(transition)
    await db.commit()
    await db.refresh(standup)

    result = await db.execute(
        select(Standup).options(selectinload(Standup.participants)).where(Standup.id == standup.id)
    )
    return result.scalar_one()


@router.get("", response_model=list[StandupListItem])
async def list_standups(domain: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(Standup).order_by(Standup.created_at.desc())
    if domain:
        query = query.where(Standup.domain == domain)
    result = await db.execute(query)
    standups = result.scalars().all()

    items = []
    for s in standups:
        count_result = await db.execute(
            select(func.count(Participant.id)).where(Participant.standup_id == s.id)
        )
        count = count_result.scalar() or 0
        item = StandupListItem(
            id=s.id,
            name=s.name,
            team_name=s.team_name,
            domain=s.domain,
            status=s.status,
            scheduled_at=s.scheduled_at,
            started_at=s.started_at,
            ended_at=s.ended_at,
            created_at=s.created_at,
            participant_count=count,
            # Without these the SPA can't distinguish a recurring session from a
            # standalone standup, so sessions wrongly appear under "One-off".
            template_id=s.template_id,
            session_number=s.session_number,
        )
        items.append(item)
    return items


@router.get("/{standup_id}", response_model=StandupRead)
async def get_standup(standup_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Standup).options(selectinload(Standup.participants)).where(Standup.id == standup_id)
    )
    standup = result.scalar_one_or_none()
    if not standup:
        raise HTTPException(status_code=404, detail="Standup not found")
    return standup
