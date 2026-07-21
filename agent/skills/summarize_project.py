"""
summarize_project skill — generates a project-manager-lens rollup for a
completed project meeting, using GPT-4o.

Shares the per-person extraction with the standup skill (agent.skills.summarize
.extract_per_person) — the difference is the *rollup* prompt: this produces a
PROJECT-level status (progress, risks, milestones, blockers) rather than a
per-teammate digest. Persists via the same MCP save_summaries tool, so the
existing summary/excel/deliver read paths work unchanged for project meetings.
"""
import logging

from shared.config import settings
from agent.mcp_config import get_mcp_tools, call_tool
from agent.gpt4o_client import summarize_project_rollup
from agent.skills.summarize import extract_per_person
from agent.prompts.project_rollup import PROMPT_VERSION as PROJECT_ROLLUP_VERSION

logger = logging.getLogger(__name__)


async def run_summarize_project(standup_id: str) -> dict:
    tools = await get_mcp_tools()

    context = await call_tool(tools, "get_standup_context", {"standup_id": standup_id})
    if not context.get("success"):
        return {"status": "failed", "error": context.get("error", "get_standup_context failed")}

    participants = context.get("participants", [])
    per_person_results, joined, full_roster, manager_info = await extract_per_person(context)

    rollup_md = await summarize_project_rollup(
        team_name=context["team_name"],
        date=context["date"],
        joined_summaries=joined,
        n=len(participants),
        manager_name=manager_info["name"],
        manager_designation=manager_info["designation"],
        manager_department=manager_info["department"],
        team_roster=full_roster,
    )

    # Project rollups are project-level; key_wins/key_blockers parsing keeps the
    # same naive heuristic as the standup path (documented weakness), reused for
    # the email/excel highlight lists.
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
            "prompt_version": PROJECT_ROLLUP_VERSION,
        },
    })

    if not save_result.get("success"):
        return {"status": "failed", "error": save_result.get("error", "save_summaries failed")}

    logger.info(
        "summarize_project complete",
        extra={"standup_id": standup_id, "participants": len(per_person_results)},
    )
    return {
        "status": "completed",
        "standup_id": standup_id,
        "participants": len(per_person_results),
        "rollup_present": True,
    }
