"""
Insights — historic / aggregated summaries over a date range.

Two shapes:
  * GET  /api/insights/meetings  — call-level: the per-meeting rollups already
    generated for each standup/project meeting in a range (direct DB read).
  * POST /api/insights/aggregate — cross-meeting rollups at a granularity
    (overall / monthly / weekly) for a scope (individual / project / overall).
    The requested range is split into buckets; each bucket is generated once by
    the domain's agent (summarize_period skill) and cached in aggregate_summaries.
    Re-requesting returns the cache unless force=true.

Data isolation note: meetings/summaries are shared across users; only Data
Entry is per-user. So aggregate rows are shared, but when a caller folds in
their Data Entry tables we pass THEIR schema, and the row records which tables
were used (data_entry_refs) so a cached row generated without Data Entry is not
silently reused for a request that asked to include it (see cache key note).
"""
import calendar
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, cast, select, Date, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.db import get_db
from shared.models import AggregateSummary, Participant, Standup, StandupSummary, StandupTemplate
from shared.schemas import AggregateRequest, AggregateSummaryRead

from ..auth import current_user
from ..a2a_registry import agent_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/insights", tags=["insights"])

_DOMAIN_AGENT = {"standup": "standup_agent", "project": "project_agent"}


# ── Date bucketing ───────────────────────────────────────────────────────────
# Monthly/weekly buckets use FULL calendar months / ISO weeks (not clipped to
# the request edges) so a "July 2026" or "week of ..." summary is stable and
# cache-shareable regardless of the enclosing request range. 'overall' uses the
# exact requested range.

def _month_buckets(start: date, end: date) -> list[tuple[date, date, str, str]]:
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        first = date(y, m, 1)
        last = date(y, m, calendar.monthrange(y, m)[1])
        out.append((first, last, f"{y:04d}-{m:02d}", first.strftime("%B %Y")))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _week_buckets(start: date, end: date) -> list[tuple[date, date, str, str]]:
    out = []
    cur = start - timedelta(days=start.weekday())  # Monday of the start's week
    while cur <= end:
        we = cur + timedelta(days=6)
        iso = cur.isocalendar()
        out.append((cur, we, f"{iso[0]:04d}-W{iso[1]:02d}", f"week of {cur.isoformat()}"))
        cur = cur + timedelta(days=7)
    return out


def _buckets(granularity: str, start: date, end: date) -> list[tuple[date, date, str, str]]:
    if granularity == "monthly":
        return _month_buckets(start, end)
    if granularity == "weekly":
        return _week_buckets(start, end)
    return [(start, end, "overall", "overall")]


def _subject_type(scope: str, subject_id: str) -> str:
    if scope == "individual":
        return "participant"
    if scope == "project":
        return "template" if subject_id else "global"
    return "global"


async def _resolve_subject_label(scope: str, subject_id: str, db: AsyncSession) -> str:
    if not subject_id:
        return ""
    if scope == "individual":
        name = (await db.execute(
            select(Participant.name).where(sqlfunc.lower(Participant.email) == subject_id.lower()).limit(1)
        )).scalar_one_or_none()
        return name or subject_id
    if scope == "project":
        name = (await db.execute(
            select(StandupTemplate.name).where(StandupTemplate.id == subject_id)
        )).scalar_one_or_none()
        return name or ""
    return ""


async def _call_period_skill(agent_name: str, skill_data: dict) -> dict:
    client = agent_registry.get_client(agent_name)
    if client is None:
        raise HTTPException(status_code=503, detail=f"{agent_name} is not configured")
    task = await client.send_task({"_skill": "summarize_period", **skill_data})
    state = task.status.state
    state = state if isinstance(state, str) else state.value
    if state != "completed":
        error_msg = "summarize_period failed"
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


# ── Call-level listing (direct DB) ───────────────────────────────────────────

@router.get("/meetings")
async def list_meeting_summaries(
    domain: str,
    range_start: date,
    range_end: date,
    subject_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Per-meeting rollups in a range (call-level). Optional subject_id filters
    to a project series (template_id)."""
    date_expr = sqlfunc.coalesce(Standup.ended_at, Standup.created_at)
    conditions = [
        Standup.domain == domain,
        cast(date_expr, Date) >= range_start,
        cast(date_expr, Date) <= range_end,
    ]
    if subject_id:
        conditions.append(Standup.template_id == subject_id)

    rows = (await db.execute(
        select(Standup, StandupSummary)
        .join(StandupSummary, StandupSummary.standup_id == Standup.id)
        .where(and_(*conditions))
        .order_by(date_expr.desc())
    )).all()

    return [
        {
            "standup_id": s.id,
            "name": s.name,
            "team_name": s.team_name,
            "date": (s.ended_at or s.created_at).strftime("%Y-%m-%d"),
            "rollup_markdown": ss.rollup_markdown,
            "key_wins": ss.key_wins,
            "key_blockers": ss.key_blockers,
        }
        for s, ss in rows
    ]


# ── Aggregate generation (agent + cache) ─────────────────────────────────────

@router.post("/aggregate", response_model=list[AggregateSummaryRead])
async def generate_aggregate(payload: AggregateRequest, request: Request, db: AsyncSession = Depends(get_db)):
    if payload.range_start > payload.range_end:
        raise HTTPException(status_code=422, detail="range_start must be on or before range_end")
    if payload.scope == "call":
        raise HTTPException(status_code=422, detail="Use GET /insights/meetings for call-level summaries")

    agent_name = _DOMAIN_AGENT.get(payload.domain)
    if not agent_name:
        raise HTTPException(status_code=422, detail=f"Unknown domain: {payload.domain}")

    subject_id = payload.subject_id or ""
    subject_type = _subject_type(payload.scope, subject_id)
    subject_label = await _resolve_subject_label(payload.scope, subject_id, db)

    dataentry_schema = ""
    if payload.dataentry_table_ids:
        dataentry_schema = current_user(request).dataentry_schema

    results: list[AggregateSummary] = []
    for bkt_start, bkt_end, bucket_key, period_label in _buckets(
        payload.granularity, payload.range_start, payload.range_end
    ):
        existing = (await db.execute(
            select(AggregateSummary).where(
                AggregateSummary.domain == payload.domain,
                AggregateSummary.scope == payload.scope,
                AggregateSummary.granularity == payload.granularity,
                AggregateSummary.range_start == bkt_start,
                AggregateSummary.range_end == bkt_end,
                AggregateSummary.subject_id == subject_id,
                AggregateSummary.bucket_key == bucket_key,
            )
        )).scalar_one_or_none()

        # Reuse the cache unless forced OR the requested Data Entry set differs
        # from what the cached row was generated with (so folding in tables isn't
        # silently ignored, and vice-versa).
        wants_refs = sorted(payload.dataentry_table_ids)
        if existing and not payload.force and sorted(existing.data_entry_refs or []) == wants_refs:
            results.append(existing)
            continue

        skill_result = await _call_period_skill(agent_name, {
            "domain": payload.domain,
            "scope": payload.scope,
            "range_start": bkt_start.isoformat(),
            "range_end": bkt_end.isoformat(),
            "subject_id": subject_id,
            "subject_label": subject_label,
            "period_label": period_label,
            "dataentry_schema": dataentry_schema,
            "dataentry_table_ids": payload.dataentry_table_ids,
        })

        rollup_md = skill_result.get("rollup_markdown", "")
        key_points = skill_result.get("key_points", [])
        prompt_version = skill_result.get("prompt_version", "aggregate-v1")

        if existing:
            existing.rollup_markdown = rollup_md
            existing.key_points = key_points
            existing.data_entry_refs = payload.dataentry_table_ids
            existing.subject_type = subject_type
            existing.model = settings.summarize_model
            existing.prompt_version = prompt_version
            existing.updated_at = datetime.now(timezone.utc)
            results.append(existing)
        else:
            row = AggregateSummary(
                domain=payload.domain,
                scope=payload.scope,
                granularity=payload.granularity,
                range_start=bkt_start,
                range_end=bkt_end,
                subject_type=subject_type,
                subject_id=subject_id,
                bucket_key=bucket_key,
                rollup_markdown=rollup_md,
                key_points=key_points,
                data_entry_refs=payload.dataentry_table_ids,
                model=settings.summarize_model,
                prompt_version=prompt_version,
            )
            db.add(row)
            results.append(row)
        await db.commit()

    for r in results:
        await db.refresh(r)
    # Chronological order for display.
    results.sort(key=lambda r: (r.range_start, r.bucket_key))
    return results
