SYSTEM = (
    "You are a concise executive summarizer preparing a standup digest for a team lead. "
    "Generate a clear, actionable digest from per-person standup summaries. "
    "Be specific — reference people by name and role. "
    "Highlight cross-team dependencies and suggested follow-ups. "
    "Do not add information not present in the inputs."
)

USER_TEMPLATE = (
    "Team: {team_name}. Date: {date}. Participants: {n}.\n"
    "{manager_context}"           # "This digest is prepared for Manoj Kumar (Team Lead).\n" or ""
    "\nTeam composition:\n{team_roster}\n"   # full roster with roles + [Manager] flag
    "\nPer-person standup updates:\n{joined_summaries}\n\n"
    "Generate a standup digest{for_manager}:\n"    # " for Manoj Kumar" or ""
    "1. A 2-3 sentence executive overview of team progress, referencing people by name and role.\n"
    "2. Key wins from yesterday — bullet list, max 5, include owner name and role.\n"
    "3. Active blockers — bullet list, max 5, include owner name, role, and potential impact.\n"
    "4. Cross-team dependencies or coordination needs between specific teammates.\n"
    "5. Suggested follow-ups or decisions for the team lead.\n\n"
    "Format as Markdown. Name people and their work. Do not hallucinate."
)

PROMPT_VERSION = "v2"


def build_manager_context(manager_name: str, manager_designation: str = "", manager_department: str = "") -> str:
    if not manager_name:
        return ""
    parts = [x for x in [manager_designation, manager_department] if x]
    role_str = f" ({', '.join(parts)})" if parts else ""
    return f"This digest is prepared for {manager_name}{role_str}.\n"


def build_full_roster(participants: list[dict]) -> str:
    """participants: list of dicts with name, designation, department, is_manager."""
    lines = []
    for p in participants:
        parts = [x for x in [p.get("designation"), p.get("department")] if x]
        role_str = f" ({', '.join(parts)})" if parts else ""
        flag = " [Manager]" if p.get("is_manager") else ""
        lines.append(f"- {p['name']}{role_str}{flag}")
    return "\n".join(lines) if lines else "No participant details available."
