"""Prompt for historic / aggregated summaries (summarize_period skill).

One call summarizes a single already-bucketed date range at a given scope:
  - individual : one teammate's cumulative work across the period (standup)
  - project    : a project's trajectory across the period (project)
  - overall    : the whole team/portfolio trajectory across the period

The orchestrator buckets the requested range by granularity (overall/weekly/
monthly) and calls this once per bucket.
"""
SYSTEM = (
    "You are an analytical summarizer producing a historic rollup across multiple "
    "meetings over a time period. Synthesize trends, cumulative progress, recurring "
    "themes, and — importantly — gaps where expected work did not happen. Be "
    "specific and grounded strictly in the provided material; never invent facts. "
    "If supplementary Data Entry tables are provided, use them as additional factual "
    "context (e.g. planned tasks, metrics) to judge progress and gaps."
)

# Per-scope instruction block spliced into the user message.
_SCOPE_INSTRUCTIONS = {
    "individual": (
        "Focus on {subject_label}. Summarize their cumulative accomplishments over "
        "the period, work in progress, recurring blockers, and any days/areas where "
        "little or no progress was reported (lack of work). Structure:\n"
        "1. Overview of the person's output this period.\n"
        "2. Key accomplishments (bulleted).\n"
        "3. Recurring or unresolved blockers (bulleted).\n"
        "4. Gaps / low-activity periods and possible reasons.\n"
    ),
    "project": (
        "Focus on the project '{subject_label}'. Summarize its trajectory over the "
        "period. Structure:\n"
        "1. Overall project status and momentum this period.\n"
        "2. Progress against goals / completed milestones (bulleted).\n"
        "3. Risks and issues that emerged or persisted (bulleted).\n"
        "4. Blockers, dependencies, and areas that stalled (bulleted).\n"
        "5. Recommended decisions / follow-ups.\n"
    ),
    "overall": (
        "Provide an overall rollup across all meetings in the period. Structure:\n"
        "1. Executive overview of overall progress and momentum.\n"
        "2. Key wins across the team/portfolio (bulleted).\n"
        "3. Cross-cutting risks and blockers (bulleted).\n"
        "4. Notable gaps or stalled areas.\n"
        "5. Recommended follow-ups.\n"
    ),
}

USER_TEMPLATE = (
    "Domain: {domain}. Scope: {scope}. Period: {period_label} "
    "({range_start} to {range_end}). Meetings in period: {n}.\n\n"
    "{scope_instructions}\n"
    "Source material — per-meeting summaries in this period:\n{items}\n"
    "{data_entry_block}\n"
    "Write the summary as Markdown. Be concise and specific. Do not hallucinate."
)

PROMPT_VERSION = "aggregate-v1"


def build_scope_instructions(scope: str, subject_label: str) -> str:
    tmpl = _SCOPE_INSTRUCTIONS.get(scope, _SCOPE_INSTRUCTIONS["overall"])
    return tmpl.format(subject_label=subject_label or "the subject")


def build_items_block(items: list[dict]) -> str:
    """items: list of {date, title, markdown} per-meeting summaries."""
    if not items:
        return "(No meeting summaries were found in this period.)"
    blocks = []
    for it in items:
        header = f"### {it.get('date', '')} — {it.get('title', '')}".rstrip(" —")
        blocks.append(f"{header}\n{it.get('markdown', '')}")
    return "\n\n".join(blocks)


def build_data_entry_block(tables: list[dict]) -> str:
    """tables: list of {display_name, columns: [display_name], rows: [ {..} ]}."""
    if not tables:
        return ""
    lines = ["\nSupplementary Data Entry context:"]
    for t in tables:
        lines.append(f"\nTable: {t.get('display_name', '')}")
        cols = t.get("columns", [])
        if cols:
            lines.append("Columns: " + ", ".join(cols))
        rows = t.get("rows", [])
        for r in rows[:50]:  # cap to keep the prompt bounded
            lines.append("- " + "; ".join(f"{k}={v}" for k, v in r.items()))
        if len(rows) > 50:
            lines.append(f"...(+{len(rows) - 50} more rows)")
    return "\n".join(lines)
