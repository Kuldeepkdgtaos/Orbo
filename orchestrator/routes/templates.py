import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from shared.db import get_db
from shared.models import StandupTemplate, TemplateParticipant, Standup, Participant, StateTransition
from shared.schemas import TemplateCreate, TemplateRead, TemplateListItem, StandupRead, StandupListItem

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/templates", tags=["templates"])


@router.post("", response_model=TemplateRead, status_code=201)
async def create_template(payload: TemplateCreate, db: AsyncSession = Depends(get_db)):
    template = StandupTemplate(
        name=payload.name,
        team_name=payload.team_name,
        meeting_url=payload.meeting_url,
        domain=payload.domain,
        management_recipients=payload.management_recipients,
    )
    db.add(template)
    await db.flush()

    for p in payload.participants:
        tp = TemplateParticipant(
            template_id=template.id,
            name=p.name,
            email=p.email,
            teams_display_name=p.teams_display_name,
            designation=p.designation,
            department=p.department,
            order_index=p.order_index,
            is_manager=p.is_manager,
        )
        db.add(tp)

    await db.commit()

    result = await db.execute(
        select(StandupTemplate)
        .options(selectinload(StandupTemplate.participants))
        .where(StandupTemplate.id == template.id)
    )
    return result.scalar_one()


@router.get("", response_model=list[TemplateListItem])
async def list_templates(domain: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(StandupTemplate).order_by(StandupTemplate.created_at.desc())
    if domain:
        query = query.where(StandupTemplate.domain == domain)
    result = await db.execute(query)
    templates = result.scalars().all()

    items = []
    for t in templates:
        p_count = (await db.execute(
            select(func.count(TemplateParticipant.id)).where(TemplateParticipant.template_id == t.id)
        )).scalar() or 0

        s_count = (await db.execute(
            select(func.count(Standup.id)).where(Standup.template_id == t.id)
        )).scalar() or 0

        items.append(TemplateListItem(
            id=t.id,
            name=t.name,
            team_name=t.team_name,
            domain=t.domain,
            created_at=t.created_at,
            participant_count=p_count,
            session_count=s_count,
        ))
    return items


@router.get("/{template_id}", response_model=TemplateRead)
async def get_template(template_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(StandupTemplate)
        .options(selectinload(StandupTemplate.participants))
        .where(StandupTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.post("/{template_id}/start-session", response_model=StandupRead, status_code=201)
async def start_session(template_id: str, db: AsyncSession = Depends(get_db)):
    """Create a new idle standup session cloned from the template. Caller then POSTs /standups/{id}/start to dispatch the bot."""
    result = await db.execute(
        select(StandupTemplate)
        .options(selectinload(StandupTemplate.participants))
        .where(StandupTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    session_count = (await db.execute(
        select(func.count(Standup.id)).where(Standup.template_id == template_id)
    )).scalar() or 0
    session_number = session_count + 1

    session = Standup(
        name=template.name,
        team_name=template.team_name,
        meeting_url=template.meeting_url,
        domain=template.domain,
        management_recipients=template.management_recipients,
        status="idle",
        template_id=template.id,
        session_number=session_number,
    )
    db.add(session)
    await db.flush()

    for tp in template.participants:
        p = Participant(
            standup_id=session.id,
            name=tp.name,
            email=tp.email,
            teams_display_name=tp.teams_display_name,
            order_index=tp.order_index,
            designation=tp.designation,
            department=tp.department,
            is_manager=tp.is_manager,
        )
        db.add(p)

    transition = StateTransition(
        standup_id=session.id,
        from_state=None,
        to_state="idle",
        event="session_created",
        metadata_={"template_id": template_id, "session_number": session_number},
    )
    db.add(transition)
    await db.commit()

    result = await db.execute(
        select(Standup)
        .options(selectinload(Standup.participants))
        .where(Standup.id == session.id)
    )
    logger.info("Session created", extra={"template_id": template_id, "session_id": session.id, "session_number": session_number})
    return result.scalar_one()


@router.get("/{template_id}/sessions", response_model=list[StandupListItem])
async def list_sessions(template_id: str, db: AsyncSession = Depends(get_db)):
    template_exists = (await db.execute(
        select(func.count(StandupTemplate.id)).where(StandupTemplate.id == template_id)
    )).scalar()
    if not template_exists:
        raise HTTPException(status_code=404, detail="Template not found")

    result = await db.execute(
        select(Standup)
        .where(Standup.template_id == template_id)
        .order_by(Standup.session_number.desc())
    )
    sessions = result.scalars().all()

    items = []
    for s in sessions:
        p_count = (await db.execute(
            select(func.count(Participant.id)).where(Participant.standup_id == s.id)
        )).scalar() or 0
        items.append(StandupListItem(
            id=s.id,
            name=s.name,
            team_name=s.team_name,
            domain=s.domain,
            status=s.status,
            scheduled_at=s.scheduled_at,
            started_at=s.started_at,
            ended_at=s.ended_at,
            created_at=s.created_at,
            participant_count=p_count,
            template_id=s.template_id,
            session_number=s.session_number,
        ))
    return items
