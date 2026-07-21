import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from shared.config import settings
from shared.db import get_db
from shared.logging import setup_logging
from shared.models import Standup, StateTransition

from .auth import require_auth
from .recall_client import recall_client
from .routes.auth import router as auth_router
from .routes.standups import router as standups_router
from .routes.templates import router as templates_router
from .routes.transcript import router as transcript_router
from .routes.summaries import router as summaries_router
from .routes.dataentry import router as dataentry_router
from .routes.insights import router as insights_router
from .state_machine import StandupStateEnum, create_initial_state, set_state, transition_state
from .webhooks import is_duplicate_event, parse_and_verify_webhook
from .chat_prompts import GREETING
from .ingest import build_utterance
from .react_agent import process_meeting

setup_logging()
logger = logging.getLogger(__name__)


# ─── Auth ─────────────────────────────────────────────────────────
# Multi-user JWT auth (see orchestrator/auth.py). The app-level dependency
# `require_auth` enforces a valid bearer token on every request except the
# exempt paths (health, /webhooks/* — Recall.ai can't send our token, any
# path ending in /stream — browser EventSource can't send headers, and the
# /api/auth/login|register endpoints themselves).

app = FastAPI(
    title="AI Standup Manager — Orchestrator",
    version="2.0.0",
    dependencies=[Depends(require_auth)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Frontend-facing routes are served under /api/* — same URL contract the
# frontend already expects (previously proxied there by the gateway).
app.include_router(auth_router, prefix="/api")
app.include_router(standups_router, prefix="/api")
app.include_router(templates_router, prefix="/api")
app.include_router(transcript_router, prefix="/api")
app.include_router(summaries_router, prefix="/api")
app.include_router(dataentry_router, prefix="/api")
app.include_router(insights_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "orchestrator"}


@app.post("/api/standups/{standup_id}/start")
async def start_standup(standup_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Standup).options(selectinload(Standup.participants)).where(Standup.id == standup_id)
    )
    standup = result.scalar_one_or_none()
    if not standup:
        raise HTTPException(status_code=404, detail="Standup not found")
    if standup.status != "idle":
        raise HTTPException(status_code=400, detail=f"Cannot start standup in state: {standup.status}")

    webhook_url = f"{settings.recall_webhook_base_url}/webhooks/recall"
    bot_data = await recall_client.create_bot(standup.meeting_url, webhook_url)
    bot_id = bot_data["id"]

    standup.status = "dispatched"
    standup.recall_bot_id = bot_id

    transition = StateTransition(
        standup_id=standup_id,
        from_state="idle",
        to_state=StandupStateEnum.BOT_DISPATCHED,
        event="start",
        metadata_={"recall_bot_id": bot_id},
    )
    db.add(transition)
    await db.commit()

    participants = [{"id": p.id, "name": p.name, "teams_display_name": p.teams_display_name} for p in standup.participants]
    state = create_initial_state(standup_id, participants, recall_bot_id=bot_id)
    state = transition_state(standup_id, StandupStateEnum.BOT_DISPATCHED, recall_bot_id=bot_id)
    set_state(standup_id, state)

    logger.info("Bot dispatched", extra={"standup_id": standup_id, "bot_id": bot_id})
    return {"status": "dispatched", "recall_bot_id": bot_id}


def _extract_bot_id(payload: dict) -> str | None:
    """Bot ID lives in different places depending on the event type."""
    data = payload.get("data", {})
    return (
        data.get("bot", {}).get("id")
        or data.get("bot_id")
        or payload.get("bot_id")
        # transcript.done: data.transcript.bot.id or data.transcript.bot_id
        or data.get("transcript", {}).get("bot", {}).get("id")
        or data.get("transcript", {}).get("bot_id")
    )


def _extract_transcript(payload: dict) -> dict:
    """Transcript data lives at data.transcript in all known Recall event shapes."""
    return payload.get("data", {}).get("transcript", {})


# Bot lifecycle events
BOT_RECORDING_EVENTS = {"bot.in_call_recording"}
BOT_WAITING_EVENTS   = {"bot.in_waiting_room", "bot.joining_call", "bot.in_call_not_recording"}
BOT_DONE_EVENTS      = {"bot.call_ended", "bot.done", "bot.fatal_error"}

# transcript.done fires when Recall has finished processing the full transcript after the meeting.
# This is the CORRECT time to fetch the transcript — not in bot.done (too early).
TRANSCRIPT_DONE_EVENTS = {"transcript.done"}

# Real-time transcript line events (only if real_time_transcription is configured)
TRANSCRIPT_REALTIME_EVENTS = {"transcript.data", "transcript.message", "transcript.realtime.message"}


def _extract_transcript_id(payload: dict) -> str | None:
    """Extract transcript ID from transcript.done event."""
    data = payload.get("data", {})
    return (
        data.get("transcript", {}).get("id")
        or data.get("transcript_id")
        or data.get("id")
    )


@app.post("/webhooks/recall")
async def recall_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await parse_and_verify_webhook(request)
    event_type = payload.get("event", "")
    event_id = payload.get("id", f"{event_type}-{id(payload)}")

    # Always log the raw event so you can see exactly what Recall is sending
    logger.info("Recall webhook received", extra={"event": event_type, "raw": json.dumps(payload)[:400]})

    if is_duplicate_event(event_id):
        return {"status": "duplicate"}

    bot_id = _extract_bot_id(payload)
    if not bot_id:
        logger.warning("Webhook payload has no bot_id", extra={"event": event_type})
        return {"status": "no_bot_id"}

    result = await db.execute(
        select(Standup).options(selectinload(Standup.participants)).where(Standup.recall_bot_id == bot_id)
    )
    standup = result.scalar_one_or_none()
    if not standup:
        logger.warning("No standup found for bot_id", extra={"bot_id": bot_id})
        return {"status": "not_found"}

    # ── Bot is joining / in lobby / joined but not recording yet ────────────
    if event_type in BOT_WAITING_EVENTS:
        logger.info("Bot status update", extra={"bot_id": bot_id, "event": event_type})
        transition = StateTransition(
            standup_id=standup.id,
            from_state=standup.status,
            to_state=StandupStateEnum.BOT_DISPATCHED,
            event=event_type,
        )
        db.add(transition)
        await db.commit()

    # ── Bot is recording — send greeting now ────────────────────────────────
    elif event_type in BOT_RECORDING_EVENTS:
        if standup.status in ("idle", "dispatched"):
            standup.status = "in_progress"
            standup.started_at = datetime.now(timezone.utc)
            transition = StateTransition(
                standup_id=standup.id,
                from_state=StandupStateEnum.BOT_DISPATCHED,
                to_state=StandupStateEnum.BOT_JOINED,
                event=event_type,
            )
            db.add(transition)
            await db.commit()
            transition_state(standup.id, StandupStateEnum.BOT_JOINED)

            try:
                await recall_client.send_chat_message(bot_id, GREETING)
                transition2 = StateTransition(
                    standup_id=standup.id,
                    from_state=StandupStateEnum.BOT_JOINED,
                    to_state=StandupStateEnum.GREETING,
                    event="greeting_sent",
                )
                db.add(transition2)
                await db.commit()
                transition_state(standup.id, StandupStateEnum.GREETING)
                logger.info("Greeting sent", extra={"bot_id": bot_id})
            except Exception as e:
                logger.error("Failed to send greeting", extra={"error": str(e), "bot_id": bot_id})

    # ── Real-time transcript line (only if real_time_transcription configured) ─
    elif event_type in TRANSCRIPT_REALTIME_EVENTS:
        transcript = _extract_transcript(payload)
        is_final = transcript.get("is_final", True)
        if not is_final:
            return {"status": "ok"}
        words = transcript.get("words", [])
        text = (transcript.get("text") or " ".join(w.get("text", "") for w in words)).strip()
        speaker = transcript.get("speaker", "Unknown")
        if text:
            logger.info("Realtime transcript line", extra={"speaker": speaker, "text": text[:120]})
            try:
                now = datetime.now(timezone.utc)
                utterance = build_utterance(
                    standup, speaker, text, now, now, transcript.get("confidence"),
                )
                db.add(utterance)
                await db.commit()
            except Exception as e:
                logger.error("Failed to ingest realtime utterance", extra={"error": str(e)}, exc_info=True)
                await db.rollback()

    # ── Call ended / bot done — just mark completed, wait for transcript.done ─
    elif event_type in BOT_DONE_EVENTS:
        if standup.status != "completed":
            previous_status = standup.status
            standup.status = "completed"
            standup.ended_at = datetime.now(timezone.utc)
            transition = StateTransition(
                standup_id=standup.id,
                from_state=previous_status,
                to_state=StandupStateEnum.COMPLETED,
                event=event_type,
            )
            db.add(transition)
            await db.commit()
            transition_state(standup.id, StandupStateEnum.COMPLETED)
            logger.info("Standup completed — waiting for transcript.done", extra={"standup_id": standup.id})

    # ── transcript.done — Recall finished processing transcript, now fetch it ─
    elif event_type in TRANSCRIPT_DONE_EVENTS:
        logger.info("transcript.done received", extra={"raw": json.dumps(payload)[:400]})

        transcript_id = _extract_transcript_id(payload)
        logger.info("Transcript ID", extra={"transcript_id": transcript_id, "bot_id": bot_id})

        try:
            transcript_data = await recall_client.get_transcript(bot_id, transcript_id=transcript_id)
            ingested = 0
            for utt in transcript_data:
                # New Recall format: speaker under participant.name; old format: utt.speaker
                speaker = (
                    utt.get("speaker")
                    or utt.get("participant", {}).get("name")
                    or "Unknown"
                )
                words = utt.get("words", [])

                # Join all words into a single utterance text (right approach for summarization)
                text = (utt.get("text") or " ".join(w.get("text", "") for w in words)).strip()
                if not text:
                    continue

                # Use actual word timestamps (new format: start_timestamp.absolute)
                now = datetime.now(timezone.utc)
                first_word = words[0] if words else {}
                last_word = words[-1] if words else {}
                started_at = (
                    first_word.get("start_timestamp", {}).get("absolute")
                    or first_word.get("start_time")
                    or now
                )
                ended_at = (
                    last_word.get("end_timestamp", {}).get("absolute")
                    or last_word.get("end_time")
                    or now
                )

                utterance = build_utterance(
                    standup, speaker, text, started_at, ended_at, utt.get("confidence"),
                )
                db.add(utterance)
                ingested += 1
                logger.info("Ingested utterance", extra={"speaker": speaker, "text": text[:80]})

            await db.commit()
            logger.info("Transcript ingested", extra={"standup_id": standup.id, "total_lines": len(transcript_data), "ingested": ingested})
        except Exception as e:
            logger.error("Failed to ingest transcript", extra={"error": str(e)}, exc_info=True)
            # A failed flush leaves the session in "pending rollback" — any
            # further use (including get_db()'s auto-commit on request
            # teardown) would raise PendingRollbackError on top of the
            # original error, turning this into a 500 that makes Recall
            # retry a webhook our event-ID dedup will then silently drop.
            await db.rollback()

        # Trigger the post-meeting A2A flow (summarize → deliver) — fire and
        # forget with retries. process_meeting drives the Tier-1 ReAct agent
        # (falling back to a deterministic sequential call on failure) and routes
        # to the Standup or Project Manager Agent based on the meeting's domain.
        async def _trigger_processing(sid: str, domain: str) -> None:
            for attempt in range(3):
                try:
                    result = await process_meeting(sid, domain)
                    logger.info("process_meeting triggered", extra={"standup_id": sid, "domain": domain, "result": result})
                    if result.get("status") == "completed":
                        return
                except Exception as e:
                    logger.warning(f"process_meeting attempt {attempt + 1} failed", extra={"error": str(e)})
                if attempt < 2:
                    await asyncio.sleep(3)
            logger.error("Failed to process meeting after 3 attempts", extra={"standup_id": sid})

        asyncio.create_task(_trigger_processing(standup.id, standup.domain))

    return {"status": "ok"}


@app.get("/api/standups/{standup_id}/stream")
async def standup_stream(standup_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    last_event_id = request.headers.get("Last-Event-ID")
    last_id = int(last_event_id) if last_event_id else 0

    async def event_generator() -> AsyncGenerator[dict, None]:
        nonlocal last_id
        # Replay missed transitions
        result = await db.execute(
            select(StateTransition)
            .where(StateTransition.standup_id == standup_id, StateTransition.id > last_id)
            .order_by(StateTransition.id)
        )
        for transition in result.scalars().all():
            yield {
                "id": str(transition.id),
                "event": "state_transition",
                "data": json.dumps({
                    "from_state": transition.from_state,
                    "to_state": transition.to_state,
                    "event": transition.event,
                    "occurred_at": transition.occurred_at.isoformat(),
                }),
            }
            last_id = transition.id

        # Poll for new transitions
        while not await request.is_disconnected():
            await asyncio.sleep(5)
            result = await db.execute(
                select(StateTransition)
                .where(StateTransition.standup_id == standup_id, StateTransition.id > last_id)
                .order_by(StateTransition.id)
            )
            for transition in result.scalars().all():
                yield {
                    "id": str(transition.id),
                    "event": "state_transition",
                    "data": json.dumps({
                        "from_state": transition.from_state,
                        "to_state": transition.to_state,
                        "event": transition.event,
                        "occurred_at": transition.occurred_at.isoformat(),
                    }),
                }
                last_id = transition.id

    return EventSourceResponse(event_generator())
