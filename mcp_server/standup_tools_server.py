"""
Standup Tools MCP Server

Exposes deterministic, DB/IO-backed tools used by the Standup Manager Agent's
skills (summarize_standup, deliver_report). This server owns NO LLM reasoning —
that lives in the agent. It only reads/writes Postgres, renders the Excel
report, and sends email via Microsoft Graph.

Tools:
  - get_standup_context : read roster + attributed transcripts for a standup
  - save_summaries      : upsert per-person + rollup summaries
  - build_excel_report  : render the Excel workbook (base64)
  - send_email          : send via Microsoft Graph
  - record_delivery     : persist an email_deliveries audit row

Used by: Standup Manager Agent (port 8020) — never exposed to the frontend
or the orchestrator directly.
"""
import sys
import os

# Ensure project root is on path when running as a subprocess / directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import base64
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy import Date, and_, cast, or_, func as sqlfunc, select, text
from sqlalchemy.orm import selectinload

from shared.config import settings
from shared.db import SessionLocal
from shared.excel_builder import build_excel
from shared.logging import setup_logging
from shared.models import (
    Standup, Participant, Utterance, ParticipantSummary, StandupSummary, EmailDelivery,
)

from mcp_server.graph_client import send_email as graph_send_email

setup_logging()
logger = logging.getLogger(__name__)

mcp = FastMCP("standup-tools", host="0.0.0.0", port=settings.mcp_port, stateless_http=True)


# ─── get_standup_context ─────────────────────────────────────────

@mcp.tool()
async def get_standup_context(standup_id: str) -> dict:
    """
    Read the full roster and attributed transcript for a standup.

    Returns the raw structured data needed to build summarization prompts —
    this tool does NOT format prose or call an LLM, it only reads the database.

    Args:
        standup_id: UUID of the standup.

    Returns:
        dict with keys:
          success (bool)
          error (str, present only on failure)
          standup_id, team_name, date (str, YYYY-MM-DD)
          management_recipients (list[str])
          manager (dict|None): {participant_id, name, designation, department}
          participants (list[dict]): each has
            participant_id, name, designation, department, is_manager, transcript (str)
    """
    async with SessionLocal() as db:
        result = await db.execute(
            select(Standup).options(selectinload(Standup.participants)).where(Standup.id == standup_id)
        )
        standup = result.scalar_one_or_none()
        if not standup:
            return {"success": False, "error": f"Standup not found: {standup_id}"}

        date_str = (standup.ended_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")

        manager = next((p for p in standup.participants if p.is_manager), None)
        manager_data = None
        if manager:
            manager_data = {
                "participant_id": manager.id,
                "name": manager.name,
                "designation": manager.designation,
                "department": manager.department,
            }

        participants_out = []
        for participant in standup.participants:
            # Primary: attributed utterances; fallback: unattributed matching by name.
            # Mirrors the original summarization_service attribution-fallback query.
            utterances_result = await db.execute(
                select(Utterance)
                .where(
                    Utterance.standup_id == standup_id,
                    or_(
                        Utterance.participant_id == participant.id,
                        (Utterance.participant_id.is_(None)) &
                        (sqlfunc.lower(Utterance.speaker_label) == participant.name.lower()),
                    ),
                )
                .order_by(Utterance.started_at)
            )
            utterances = utterances_result.scalars().all()
            transcript = " ".join(u.text for u in utterances)

            participants_out.append({
                "participant_id": participant.id,
                "name": participant.name,
                "designation": participant.designation,
                "department": participant.department,
                "is_manager": participant.is_manager,
                "transcript": transcript,
            })

        return {
            "success": True,
            "standup_id": standup_id,
            "team_name": standup.team_name,
            "date": date_str,
            "management_recipients": standup.management_recipients or [],
            "manager": manager_data,
            "participants": participants_out,
        }


# ─── save_summaries ──────────────────────────────────────────────

@mcp.tool()
async def save_summaries(standup_id: str, per_person: list, rollup: dict) -> dict:
    """
    Upsert per-person summaries and the rollup summary for a standup.

    Args:
        standup_id: UUID of the standup.
        per_person: list of dicts, each with keys:
          participant_id, yesterday, today, blockers, raw_response (dict),
          model, prompt_version
        rollup: dict with keys:
          rollup_markdown, key_wins (list), key_blockers (list), model, prompt_version

    Returns:
        dict with keys: success (bool), participants_saved (int), rollup_saved (bool), error (str, on failure)
    """
    async with SessionLocal() as db:
        standup_exists = (await db.execute(
            select(sqlfunc.count(Standup.id)).where(Standup.id == standup_id)
        )).scalar()
        if not standup_exists:
            return {"success": False, "error": f"Standup not found: {standup_id}"}

        saved = 0
        for entry in per_person:
            participant_id = entry["participant_id"]
            existing = await db.execute(
                select(ParticipantSummary).where(
                    ParticipantSummary.standup_id == standup_id,
                    ParticipantSummary.participant_id == participant_id,
                )
            )
            ps = existing.scalar_one_or_none()
            if ps:
                ps.yesterday = entry.get("yesterday", "")
                ps.today = entry.get("today", "")
                ps.blockers = entry.get("blockers", "")
                ps.raw_response = entry.get("raw_response")
                ps.model = entry.get("model", ps.model)
                ps.prompt_version = entry.get("prompt_version", ps.prompt_version)
            else:
                db.add(ParticipantSummary(
                    standup_id=standup_id,
                    participant_id=participant_id,
                    yesterday=entry.get("yesterday", ""),
                    today=entry.get("today", ""),
                    blockers=entry.get("blockers", ""),
                    raw_response=entry.get("raw_response"),
                    model=entry.get("model", "unknown"),
                    prompt_version=entry.get("prompt_version", "unknown"),
                ))
            saved += 1

        existing_ss = await db.execute(select(StandupSummary).where(StandupSummary.standup_id == standup_id))
        ss = existing_ss.scalar_one_or_none()
        if ss:
            ss.rollup_markdown = rollup.get("rollup_markdown", "")
            ss.key_blockers = rollup.get("key_blockers", [])
            ss.key_wins = rollup.get("key_wins", [])
            ss.model = rollup.get("model", ss.model)
            ss.prompt_version = rollup.get("prompt_version", ss.prompt_version)
        else:
            db.add(StandupSummary(
                standup_id=standup_id,
                rollup_markdown=rollup.get("rollup_markdown", ""),
                key_blockers=rollup.get("key_blockers", []),
                key_wins=rollup.get("key_wins", []),
                model=rollup.get("model", "unknown"),
                prompt_version=rollup.get("prompt_version", "unknown"),
            ))

        await db.commit()
        return {"success": True, "participants_saved": saved, "rollup_saved": True}


# ─── build_excel_report ──────────────────────────────────────────

EXCEL_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@mcp.tool()
async def build_excel_report(standup_id: str) -> dict:
    """
    Build the Excel workbook (Rollup + Per Person + Full Transcript sheets)
    for a standup. Requires save_summaries to have already run.

    Args:
        standup_id: UUID of the standup.

    Also returns the rollup fields (team_name, date, management_recipients,
    rollup_markdown, key_wins, key_blockers) so the deliver_report skill can
    compose the email without a second round trip.

    Returns:
        dict with keys:
          success (bool), filename (str), attachment_b64 (str), content_type (str),
          team_name (str), date (str), management_recipients (list[str]),
          rollup_markdown (str), key_wins (list), key_blockers (list)
          error (str, present only on failure)
    """
    async with SessionLocal() as db:
        result = await db.execute(
            select(Standup).options(selectinload(Standup.participants)).where(Standup.id == standup_id)
        )
        standup = result.scalar_one_or_none()
        if not standup:
            return {"success": False, "error": f"Standup not found: {standup_id}"}

        ss_result = await db.execute(select(StandupSummary).where(StandupSummary.standup_id == standup_id))
        standup_summary = ss_result.scalar_one_or_none()
        if not standup_summary:
            return {"success": False, "error": "Summaries not generated yet — call summarize_standup first"}

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

        return {
            "success": True,
            "filename": f"standup_{date_str}.xlsx",
            "attachment_b64": base64.b64encode(excel_bytes).decode(),
            "content_type": EXCEL_CONTENT_TYPE,
            "team_name": standup.team_name,
            "date": date_str,
            "management_recipients": standup.management_recipients or [],
            "rollup_markdown": standup_summary.rollup_markdown,
            "key_wins": standup_summary.key_wins,
            "key_blockers": standup_summary.key_blockers,
        }


# ─── send_email ──────────────────────────────────────────────────

@mcp.tool()
async def send_email(
    recipient_emails: list,
    subject: str,
    html_body: str,
    attachment_b64: str,
    attachment_filename: str = "report.xlsx",
) -> dict:
    """
    Send the standup digest email via Microsoft Graph, with the Excel report attached.

    Args:
        recipient_emails: list of management recipient email addresses.
        subject: email subject line.
        html_body: HTML-rendered email body (the rollup digest).
        attachment_b64: base64-encoded Excel workbook (from build_excel_report).
        attachment_filename: filename for the attachment.

    Returns:
        dict with keys: success (bool), message_id (str|None), error (str, on failure)
    """
    if not recipient_emails:
        return {"success": False, "error": "No recipient emails provided"}
    if not settings.ms_graph_tenant_id or not settings.ms_graph_client_id or not settings.ms_graph_sender_email:
        return {"success": False, "error": "Microsoft Graph is not configured (MS_GRAPH_* env vars empty)"}

    try:
        attachment_bytes = base64.b64decode(attachment_b64)
        message_id = await graph_send_email(
            to_recipients=recipient_emails,
            subject=subject,
            html_body=html_body,
            attachment_bytes=attachment_bytes,
            attachment_name=attachment_filename,
        )
        return {"success": True, "message_id": message_id}
    except Exception as e:
        logger.error("send_email failed", extra={"error": str(e), "recipients": recipient_emails})
        return {"success": False, "error": str(e)}


# ─── record_delivery ─────────────────────────────────────────────

@mcp.tool()
async def record_delivery(
    standup_id: str,
    recipients: list,
    subject: str,
    body_preview: str,
    status: str,
    message_id: Optional[str] = None,
    error: Optional[str] = None,
) -> dict:
    """
    Persist an audit record of an email delivery attempt.

    Args:
        standup_id: UUID of the standup.
        recipients: list of recipient email addresses.
        subject: email subject line that was sent.
        body_preview: short preview of the email body (e.g. first 200 chars of rollup).
        status: "sent" or "failed".
        message_id: Microsoft Graph message id, if sent successfully.
        error: error message, if the send failed.

    Returns:
        dict with keys: success (bool), delivery_id (str), sent_at (str)
    """
    async with SessionLocal() as db:
        delivery = EmailDelivery(
            standup_id=standup_id,
            recipients=recipients,
            subject=subject,
            body_preview=body_preview[:200],
            graph_message_id=message_id,
            status=status,
            error=error,
        )
        db.add(delivery)
        await db.commit()
        await db.refresh(delivery)
        return {
            "success": True,
            "delivery_id": delivery.id,
            "sent_at": delivery.sent_at.isoformat(),
        }


# ─── get_period_context ──────────────────────────────────────────
# Feeds the summarize_period (aggregate/historic) skill: the per-meeting
# summaries in a date range for a scope. Deterministic reads only.

def _period_date(standup: Standup) -> str:
    return (standup.ended_at or standup.created_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


@mcp.tool()
async def get_period_context(
    domain: str,
    scope: str,
    range_start: str,
    range_end: str,
    subject_id: str = "",
) -> dict:
    """
    Read the per-meeting summaries in a date range for aggregation.

    Args:
        domain: 'standup' | 'project' — which meetings to include.
        scope:  'individual' | 'project' | 'overall'.
                - individual: subject_id is a participant EMAIL (stable identity
                  across sessions); returns that person's per-meeting updates.
                - project: subject_id is a template_id (project series); omit for
                  the whole project portfolio. Returns per-meeting rollups.
                - overall: all meetings in the domain+range; per-meeting rollups.
        range_start, range_end: inclusive ISO dates (YYYY-MM-DD).
        subject_id: see scope above (optional).

    Returns:
        dict: success (bool), items (list of {date, title, markdown}),
              subject_label (str), count (int), error (str on failure)
    """
    try:
        rs = datetime.strptime(range_start, "%Y-%m-%d").date()
        re_ = datetime.strptime(range_end, "%Y-%m-%d").date()
    except ValueError:
        return {"success": False, "error": "range_start/range_end must be YYYY-MM-DD"}

    async with SessionLocal() as db:
        date_expr = sqlfunc.coalesce(Standup.ended_at, Standup.created_at)
        conditions = [
            Standup.domain == domain,
            cast(date_expr, Date) >= rs,
            cast(date_expr, Date) <= re_,
        ]
        if scope == "project" and subject_id:
            conditions.append(Standup.template_id == subject_id)

        standups = (await db.execute(
            select(Standup).where(and_(*conditions)).order_by(date_expr)
        )).scalars().all()
        standup_ids = [s.id for s in standups]

        items: list[dict] = []
        subject_label = ""

        if scope == "individual":
            if standup_ids and subject_id:
                rows = (await db.execute(
                    select(ParticipantSummary, Participant, Standup)
                    .join(Participant, ParticipantSummary.participant_id == Participant.id)
                    .join(Standup, ParticipantSummary.standup_id == Standup.id)
                    .where(
                        ParticipantSummary.standup_id.in_(standup_ids),
                        sqlfunc.lower(Participant.email) == subject_id.lower(),
                    )
                    .order_by(sqlfunc.coalesce(Standup.ended_at, Standup.created_at))
                )).all()
                for ps, p, s in rows:
                    subject_label = p.name
                    md = (f"Yesterday: {ps.yesterday}\nToday: {ps.today}\n"
                          f"Blockers: {ps.blockers or 'None'}")
                    items.append({"date": _period_date(s), "title": s.name, "markdown": md})
        else:
            summaries = {}
            if standup_ids:
                srows = (await db.execute(
                    select(StandupSummary).where(StandupSummary.standup_id.in_(standup_ids))
                )).scalars().all()
                summaries = {ss.standup_id: ss for ss in srows}
            for s in standups:
                ss = summaries.get(s.id)
                if not ss:
                    continue
                items.append({"date": _period_date(s), "title": s.name, "markdown": ss.rollup_markdown})
            if scope == "project" and subject_id and standups:
                subject_label = standups[0].name

        return {"success": True, "items": items, "subject_label": subject_label, "count": len(items)}


# ─── get_dataentry_context ───────────────────────────────────────
# Reads selected per-user Data Entry tables so the aggregate skill can fold
# user-supplied facts (planned tasks, metrics, ...) into a summary. Reads only.

_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def _safe_ident(ident: str) -> str:
    if not ident or len(ident) > 63 or not _IDENT_RE.match(ident):
        raise ValueError(f"Invalid identifier: {ident!r}")
    return ident


@mcp.tool()
async def get_dataentry_context(schema_name: str, table_ids: list) -> dict:
    """
    Read selected Data Entry tables (columns + rows) from a user's schema.

    Args:
        schema_name: the user's dataentry_<...> schema (validated as an identifier).
        table_ids: list of Data Entry table ids (UUID strings) to include.

    Returns:
        dict: success (bool), tables (list of {display_name, columns, rows}),
              error (str on failure). Row keys use column display names.
    """
    try:
        s = _safe_ident(schema_name)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    try:
        async with SessionLocal() as db:
            tables_out = []
            for tid in table_ids or []:
                meta = (await db.execute(
                    text(f'SELECT physical_name, display_name FROM "{s}"."_dataentry_tables" WHERE id = :tid'),
                    {"tid": tid},
                )).mappings().first()
                if not meta:
                    continue
                cols = (await db.execute(
                    text(f'SELECT physical_name, display_name FROM "{s}"."_dataentry_columns" '
                         "WHERE table_id = :tid ORDER BY order_index"),
                    {"tid": tid},
                )).mappings().all()

                phys_table = _safe_ident(meta["physical_name"])
                col_idents = [_safe_ident(c["physical_name"]) for c in cols]
                disp = {c["physical_name"]: c["display_name"] for c in cols}

                out_rows = []
                if col_idents:
                    # Cast every column to text so numeric/date/timestamp values
                    # are JSON-serializable in the MCP result (they're only used
                    # as prompt context) and never Decimal/date/datetime objects.
                    select_cols = ", ".join(f'"{c}"::text AS "{c}"' for c in col_idents)
                    rows = (await db.execute(
                        text(f'SELECT {select_cols} FROM "{s}"."{phys_table}" ORDER BY created_at')
                    )).mappings().all()
                    out_rows = [{disp.get(k, k): v for k, v in dict(r).items()} for r in rows]

                tables_out.append({
                    "display_name": meta["display_name"],
                    "columns": [c["display_name"] for c in cols],
                    "rows": out_rows,
                })
            return {"success": True, "tables": tables_out}
    except Exception as e:
        logger.error("get_dataentry_context failed", extra={"error": str(e)})
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
