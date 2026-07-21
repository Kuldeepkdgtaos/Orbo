"""
summarize_period skill — historic / aggregated summary over one date-range
bucket, at a given scope (individual | project | overall).

Deterministic pipeline (no ReAct):
  1. MCP get_period_context   → in-range per-meeting summaries (+ subject label)
  2. MCP get_dataentry_context → optional user Data Entry tables (if requested)
  3. GPT-4o aggregate          → one markdown rollup
The orchestrator's insights route buckets the requested range by granularity
and calls this once per bucket, caching each result in aggregate_summaries.
"""
import logging

from agent.mcp_config import get_mcp_tools, call_tool
from agent.gpt4o_client import summarize_period_aggregate
from agent.prompts.aggregate import PROMPT_VERSION as AGGREGATE_VERSION

logger = logging.getLogger(__name__)


def _extract_key_points(markdown_text: str) -> list[str]:
    points = []
    for line in markdown_text.split("\n"):
        s = line.strip()
        if s.startswith(("- ", "* ")):
            points.append(s[2:].strip())
    return points[:10]


async def run_aggregate(data: dict) -> dict:
    domain = data.get("domain", "standup")
    scope = data.get("scope", "overall")
    range_start = data.get("range_start", "")
    range_end = data.get("range_end", "")
    subject_id = data.get("subject_id", "") or ""
    subject_label = data.get("subject_label", "") or ""
    period_label = data.get("period_label", "overall") or "overall"
    dataentry_schema = data.get("dataentry_schema", "") or ""
    dataentry_table_ids = data.get("dataentry_table_ids", []) or []

    if not range_start or not range_end:
        return {"status": "failed", "error": "range_start and range_end are required"}

    tools = await get_mcp_tools()

    context = await call_tool(tools, "get_period_context", {
        "domain": domain,
        "scope": scope,
        "range_start": range_start,
        "range_end": range_end,
        "subject_id": subject_id,
    })
    if not context.get("success"):
        return {"status": "failed", "error": context.get("error", "get_period_context failed")}

    items = context.get("items", [])
    subject_label = context.get("subject_label") or subject_label

    # Optional Data Entry context to fold into the aggregate.
    data_entry_tables = []
    if dataentry_schema and dataentry_table_ids:
        de = await call_tool(tools, "get_dataentry_context", {
            "schema_name": dataentry_schema,
            "table_ids": dataentry_table_ids,
        })
        if de.get("success"):
            data_entry_tables = de.get("tables", [])
        else:
            logger.warning("get_dataentry_context failed", extra={"error": de.get("error")})

    if not items and not data_entry_tables:
        return {
            "status": "completed",
            "rollup_markdown": f"_No meetings found for {period_label} ({range_start} to {range_end})._",
            "key_points": [],
            "meetings": 0,
            "prompt_version": AGGREGATE_VERSION,
        }

    rollup_md = await summarize_period_aggregate(
        domain=domain,
        scope=scope,
        period_label=period_label,
        range_start=range_start,
        range_end=range_end,
        items=items,
        subject_label=subject_label,
        data_entry_tables=data_entry_tables,
    )

    logger.info(
        "summarize_period complete",
        extra={"domain": domain, "scope": scope, "period": period_label, "meetings": len(items)},
    )
    return {
        "status": "completed",
        "rollup_markdown": rollup_md,
        "key_points": _extract_key_points(rollup_md),
        "meetings": len(items),
        "subject_label": subject_label,
        "prompt_version": AGGREGATE_VERSION,
    }
