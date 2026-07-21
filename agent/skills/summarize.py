"""
summarize_standup skill — generates per-person summaries and a management
rollup for a completed standup, using GPT-4o.

Pipeline (deterministic, no ReAct loop):
  1. MCP get_standup_context  → roster + attributed transcripts
  2. GPT-4o per-person extraction (one call per participant)
  3. GPT-4o rollup digest (one call, fed the per-person summaries)
  4. MCP save_summaries       → persist everything

Unchanged from the pre-migration summarization_service in behavior: same
prompts, same JSON-mode extraction, same key_wins/key_blockers parsing.
"""
import logging

from shared.config import settings
from agent.mcp_config import get_mcp_tools, call_tool
from agent.gpt4o_client import summarize_person, summarize_rollup
from agent.prompts.per_person import PROMPT_VERSION as PER_PERSON_VERSION, build_team_roster_for_person
from agent.prompts.rollup import PROMPT_VERSION as ROLLUP_VERSION, build_full_roster

logger = logging.getLogger(__name__)


async def extract_per_person(context: dict) -> tuple[list[dict], str, str, dict]:
    """Run the GPT-4o per-person extraction over a meeting's roster+transcripts.

    Shared by the standup (summarize_standup) and project (summarize_project)
    skills — only the *rollup* prompt differs between them, the per-person
    extraction is identical. Returns:
      (per_person_results, joined_summaries_text, full_roster_str, manager_info)
    where manager_info is {name, designation, department}.
    """
    participants = context.get("participants", [])
    manager = context.get("manager")
    manager_name = manager["name"] if manager else ""
    manager_designation = manager.get("designation", "") if manager else ""
    manager_department = manager.get("department", "") if manager else ""

    full_roster = build_full_roster([
        {
            "name": p["name"],
            "designation": p.get("designation"),
            "department": p.get("department"),
            "is_manager": p.get("is_manager", False),
        }
        for p in participants
    ])

    per_person_results = []
    summaries_text = []

    for participant in participants:
        transcript = participant.get("transcript", "")

        teammates = [
            {
                "name": p["name"],
                "designation": p.get("designation"),
                "department": p.get("department"),
            }
            for p in participants
            if p["participant_id"] != participant["participant_id"]
        ]
        team_roster_str = build_team_roster_for_person(teammates)

        if not transcript.strip():
            logger.warning(
                "No transcript for participant",
                extra={"participant_id": participant["participant_id"], "participant_name": participant["name"]},
            )
            raw = {"yesterday": "", "today": "", "blockers": ""}
        else:
            raw = await summarize_person(
                participant["name"],
                context["date"],
                transcript,
                designation=participant.get("designation"),
                department=participant.get("department"),
                manager_name=manager_name,
                team_roster=team_roster_str,
            )

        per_person_results.append({
            "participant_id": participant["participant_id"],
            "yesterday": raw.get("yesterday", ""),
            "today": raw.get("today", ""),
            "blockers": raw.get("blockers", ""),
            "raw_response": raw,
            "model": settings.summarize_model,
            "prompt_version": PER_PERSON_VERSION,
        })

        role_parts = [x for x in [participant.get("designation"), participant.get("department")] if x]
        role_str = f" ({', '.join(role_parts)})" if role_parts else ""
        summaries_text.append(
            f"**{participant['name']}**{role_str}\n"
            f"Yesterday: {raw.get('yesterday', '')}\n"
            f"Today: {raw.get('today', '')}\n"
            f"Blockers: {raw.get('blockers', '') or 'None'}"
        )

    joined = "\n\n".join(summaries_text)
    manager_info = {
        "name": manager_name,
        "designation": manager_designation,
        "department": manager_department,
    }
    return per_person_results, joined, full_roster, manager_info


async def run_summarize(standup_id: str) -> dict:
    tools = await get_mcp_tools()

    context = await call_tool(tools, "get_standup_context", {"standup_id": standup_id})
    if not context.get("success"):
        return {"status": "failed", "error": context.get("error", "get_standup_context failed")}

    participants = context.get("participants", [])
    per_person_results, joined, full_roster, manager_info = await extract_per_person(context)
    manager_name = manager_info["name"]
    manager_designation = manager_info["designation"]
    manager_department = manager_info["department"]

    rollup_md = await summarize_rollup(
        team_name=context["team_name"],
        date=context["date"],
        joined_summaries=joined,
        n=len(participants),
        manager_name=manager_name,
        manager_designation=manager_designation,
        manager_department=manager_department,
        team_roster=full_roster,
    )

    key_wins = [line.strip("- ") for line in rollup_md.split("\n") if "win" in line.lower() and line.startswith("-")][:5]
    key_blockers = [line.strip("- ") for line in rollup_md.split("\n") if "blocker" in line.lower() and line.startswith("-")][:5]

    save_result = await call_tool(tools, "save_summaries", {
        "standup_id": standup_id,
        "per_person": per_person_results,
        "rollup": {
            "rollup_markdown": rollup_md,
            "key_wins": key_wins,
            "key_blockers": key_blockers,
            "model": settings.summarize_model,
            "prompt_version": ROLLUP_VERSION,
        },
    })

    if not save_result.get("success"):
        return {"status": "failed", "error": save_result.get("error", "save_summaries failed")}

    logger.info(
        "summarize_standup complete",
        extra={"standup_id": standup_id, "participants": len(per_person_results)},
    )
    return {
        "status": "completed",
        "standup_id": standup_id,
        "participants": len(per_person_results),
        "rollup_present": True,
    }
