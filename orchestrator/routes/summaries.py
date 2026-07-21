"""
Summary reads (direct DB — fast, no reasoning needed) and delivery actions
(routed through the Standup Manager Agent via A2A — these are the mutating,
agentic operations: summarize_standup writes AI-generated content,
deliver_report sends an email and records the delivery).
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.db import get_db
from shared.models import Standup, Utterance, ParticipantSummary, StandupSummary
from shared.schemas import ParticipantSummaryRead, StandupSummaryRead
from shared.excel_builder import build_excel

from ..a2a_registry import agent_registry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["summaries"])

EXCEL_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ─── Reads (direct DB) ────────────────────────────────────────────

@router.get("/standups/{standup_id}/summary", response_model=StandupSummaryRead)
async def get_summary(standup_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StandupSummary).where(StandupSummary.standup_id == standup_id))
    ss = result.scalar_one_or_none()
    if not ss:
        raise HTTPException(status_code=404, detail="Summary not found")
    return ss


@router.get("/standups/{standup_id}/participant-summaries", response_model=list[ParticipantSummaryRead])
async def get_participant_summaries(standup_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ParticipantSummary).where(ParticipantSummary.standup_id == standup_id))
    return result.scalars().all()


@router.get("/standups/{standup_id}/excel")
async def download_excel(standup_id: str, db: AsyncSession = Depends(get_db)):
    """
    Direct DB + shared.excel_builder render — unchanged behavior from before
    the migration. This is a pure, deterministic file render (no LLM
    reasoning involved), so it does not need an A2A round trip through the
    agent; it reuses the exact same shared.excel_builder module the agent's
    build_excel_report MCP tool calls.
    """
    result = await db.execute(
        select(Standup).options(selectinload(Standup.participants)).where(Standup.id == standup_id)
    )
    standup = result.scalar_one_or_none()
    if not standup:
        raise HTTPException(status_code=404, detail="Standup not found")

    ss_result = await db.execute(select(StandupSummary).where(StandupSummary.standup_id == standup_id))
    standup_summary = ss_result.scalar_one_or_none()
    if not standup_summary:
        raise HTTPException(status_code=422, detail="Summaries not generated yet")

    per_person = []
    for p in standup.participants:
        ps_result = await db.execute(
            select(ParticipantSummary).where(
                ParticipantSummary.standup_id == standup_id,
                ParticipantSummary.participant_id == p.id,
            )
        )
        ps = ps_result.scalar_one_or_none()
        per_person.append({
            "name": p.name,
            "yesterday": ps.yesterday if ps else "",
            "today": ps.today if ps else "",
            "blockers": ps.blockers if ps else "",
        })

    utterances_result = await db.execute(
        select(Utterance).where(Utterance.standup_id == standup_id).order_by(Utterance.started_at)
    )
    utterances = [
        {"started_at": u.started_at.isoformat(), "speaker_label": u.speaker_label, "text": u.text}
        for u in utterances_result.scalars().all()
    ]

    date_str = (standup.ended_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    excel_bytes = build_excel(
        standup_name=standup.name,
        team_name=standup.team_name,
        date=date_str,
        rollup_markdown=standup_summary.rollup_markdown,
        key_wins=standup_summary.key_wins,
        key_blockers=standup_summary.key_blockers,
        per_person=per_person,
        utterances=utterances,
    )

    return Response(
        content=excel_bytes,
        media_type=EXCEL_CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="standup_{date_str}.xlsx"'},
    )


# ─── Actions (via A2A) ────────────────────────────────────────────

# Which agent + skills handle each meeting domain. Mirrors react_agent._DOMAIN_ROUTING.
_DOMAIN_ROUTING = {
    "standup": {"agent": "standup_agent", "summarize": "summarize_standup", "deliver": "deliver_report"},
    "project": {"agent": "project_agent", "summarize": "summarize_project", "deliver": "deliver_project_report"},
}


async def _meeting_domain(standup_id: str, db: AsyncSession) -> str:
    domain = (await db.execute(select(Standup.domain).where(Standup.id == standup_id))).scalar_one_or_none()
    if domain is None:
        raise HTTPException(status_code=404, detail="Standup not found")
    return domain


async def _call_agent_skill(agent_name: str, skill: str, standup_id: str, **extra) -> dict:
    client = agent_registry.get_client(agent_name)
    if client is None:
        raise HTTPException(status_code=503, detail=f"{agent_name} is not configured")

    task = await client.send_task({"_skill": skill, "standup_id": standup_id, **extra})
    state = task.status.state
    state = state if isinstance(state, str) else state.value

    if state != "completed":
        error_msg = f"{skill} failed"
        if task.status.message and task.status.message.parts:
            for part in task.status.message.parts:
                p = part if isinstance(part, dict) else part.model_dump()
                if p.get("kind") == "text":
                    error_msg = p.get("text", error_msg)
                    break
        raise HTTPException(status_code=502, detail=error_msg)

    for artifact in task.artifacts:
        art = artifact if isinstance(artifact, dict) else artifact.model_dump()
        for part in art.get("parts", []):
            if part.get("kind") == "data":
                return part.get("data", {})
    return {"status": "completed"}


@router.post("/standups/{standup_id}/regenerate", status_code=202)
async def regenerate_summary(standup_id: str, db: AsyncSession = Depends(get_db)):
    """Manual re-run of the domain's summarize skill via A2A."""
    route = _DOMAIN_ROUTING[await _meeting_domain(standup_id, db)]
    return await _call_agent_skill(route["agent"], route["summarize"], standup_id)


@router.post("/standups/{standup_id}/deliver")
async def deliver(standup_id: str, db: AsyncSession = Depends(get_db)):
    """Build the Excel report and email it via the domain's deliver skill."""
    route = _DOMAIN_ROUTING[await _meeting_domain(standup_id, db)]
    return await _call_agent_skill(route["agent"], route["deliver"], standup_id)


@router.post("/standups/{standup_id}/resend-email")
async def resend_email(standup_id: str, db: AsyncSession = Depends(get_db)):
    """Resend the digest email via the domain's deliver skill (force_resend=True)."""
    route = _DOMAIN_ROUTING[await _meeting_domain(standup_id, db)]
    return await _call_agent_skill(route["agent"], route["deliver"], standup_id, force_resend=True)
