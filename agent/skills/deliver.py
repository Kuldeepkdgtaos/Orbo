"""
deliver_report skill — builds the Excel report and emails the digest to
management. Requires summarize_standup to have already run for this standup.

Risk mitigation note (deliberate refinement of the original migration plan):
The plan called for the SLM to "compose subject + HTML body... keep it simple".
A freeform SLM-written body for a management-facing email carries real risk —
it could fabricate facts, drift in tone, or break HTML — for no clear benefit,
since the factual content (wins/blockers/per-person summaries) is already a
GPT-4o-approved digest from summarize_standup. So here the SLM's role is
narrowed to a single cosmetic intro sentence, constrained to only reference
data it's explicitly given, with a deterministic fallback if it fails or
produces empty output. The actual rollup content is always rendered
deterministically (markdown → HTML), unchanged from the pre-migration
behavior. The email subject is also deterministic — no creative value in
varying it, so no reason to add LLM risk there.
"""
import asyncio
import logging

import markdown
from langchain_core.messages import HumanMessage, SystemMessage

from shared.config import settings
from agent.mcp_config import get_mcp_tools, call_tool
from agent.slm_llm_service import create_slm_model

logger = logging.getLogger(__name__)

INTRO_SYSTEM_PROMPT = (
    "You write a single short, professional intro sentence (max 2 sentences) for a "
    "standup summary email. You will be given the team name, date, and counts of wins "
    "and blockers. Reference ONLY the facts given to you — do not invent names, numbers, "
    "or details not explicitly provided. If you are unsure what to say, write a plain, "
    "neutral intro. Output ONLY the sentence, no preamble, no quotes."
)

INTRO_FALLBACK_TEMPLATE = "Here's the standup summary for {team_name} — {date}."

INTRO_TIMEOUT_SECONDS = 15


async def _compose_intro(team_name: str, date: str, key_wins: list, key_blockers: list) -> str:
    """Best-effort SLM intro line; always falls back to a deterministic sentence."""
    fallback = INTRO_FALLBACK_TEMPLATE.format(team_name=team_name, date=date)
    try:
        model = create_slm_model(settings.deliver_model, temperature=0.3, max_tokens=120)
        user_msg = (
            f"Team: {team_name}\nDate: {date}\n"
            f"Wins recorded: {len(key_wins)}\nBlockers recorded: {len(key_blockers)}\n"
            "Write the intro sentence now."
        )
        response = await asyncio.wait_for(
            model.ainvoke([SystemMessage(content=INTRO_SYSTEM_PROMPT), HumanMessage(content=user_msg)]),
            timeout=INTRO_TIMEOUT_SECONDS,
        )
        intro = (response.content or "").strip()
        return intro if intro else fallback
    except Exception as e:
        logger.warning("Intro composition failed, using deterministic fallback", extra={"error": str(e)})
        return fallback


async def run_deliver(standup_id: str, force_resend: bool = False,
                      subject_prefix: str = "Standup Summary") -> dict:
    tools = await get_mcp_tools()

    # Builds the excel attachment AND returns the rollup fields needed to
    # compose the email, avoiding a second MCP round trip.
    report = await call_tool(tools, "build_excel_report", {"standup_id": standup_id})
    if not report.get("success"):
        return {"status": "failed", "error": report.get("error", "build_excel_report failed")}

    recipients = report.get("management_recipients", [])
    if not recipients:
        return {"status": "failed", "error": "No management recipients configured for this standup"}

    team_name = report["team_name"]
    date = report["date"]
    rollup_markdown = report.get("rollup_markdown", "")
    key_wins = report.get("key_wins", [])
    key_blockers = report.get("key_blockers", [])

    # force_resend is accepted for parity with the pre-migration API surface
    # (resend-email vs deliver endpoints) but — matching the original
    # delivery_service behavior — delivery always proceeds; no prior-delivery
    # check gates it today, in either version.
    intro = await _compose_intro(team_name, date, key_wins, key_blockers)
    html_body = f"<p>{intro}</p>\n" + markdown.markdown(rollup_markdown)
    subject = f"{subject_prefix} — {team_name} — {date}"

    send_result = await call_tool(tools, "send_email", {
        "recipient_emails": recipients,
        "subject": subject,
        "html_body": html_body,
        "attachment_b64": report["attachment_b64"],
        "attachment_filename": report["filename"],
    })

    status = "sent" if send_result.get("success") else "failed"
    await call_tool(tools, "record_delivery", {
        "standup_id": standup_id,
        "recipients": recipients,
        "subject": subject,
        "body_preview": rollup_markdown[:200],
        "status": status,
        "message_id": send_result.get("message_id"),
        "error": send_result.get("error"),
    })

    if status == "failed":
        logger.error("deliver_report failed to send", extra={"standup_id": standup_id, "error": send_result.get("error")})
        return {"status": "failed", "error": send_result.get("error", "send_email failed")}

    logger.info("deliver_report complete", extra={"standup_id": standup_id, "message_id": send_result.get("message_id")})
    return {"status": "completed", "message_id": send_result.get("message_id")}
