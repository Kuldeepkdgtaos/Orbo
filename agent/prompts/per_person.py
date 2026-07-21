from typing import Optional

SYSTEM = (
    "You are a precise standup summarizer. Extract structured information from a teammate's spoken update. "
    "Return ONLY valid JSON. Do not hallucinate — if something isn't mentioned, return an empty string for that field. "
    "When role, department, or team context is provided, frame the participant's updates in terms relevant to their "
    "function and the team they work in. "
    "IMPORTANT: The transcript may be in any language (Tamil, Hindi, etc.). Always output the JSON values in English, "
    "translating the content if necessary. Never return non-English text in the output fields."
)

USER_TEMPLATE = (
    "Below is {name}'s standup update from {date}.\n"
    "{context_line}"       # "Context: Senior Engineer, Platform.\n" or ""
    "{manager_line}"       # "This standup is reviewed by Manoj Kumar.\n" or ""
    "{team_roster}"        # "Teammates:\n- Narendra (UI UX · Inventara)\n" or ""
    "Extract:\n"
    "- yesterday: what they completed yesterday (1-3 sentences)\n"
    "- today: what they're working on today (1-3 sentences)\n"
    "- blockers: any blockers or asks for help (empty string if none)\n\n"
    "Transcript:\n{transcript}\n\n"
    'Return JSON: {{"yesterday": "...", "today": "...", "blockers": "..."}}'
)

PROMPT_VERSION = "v3"


def build_context_line(designation: Optional[str], department: Optional[str]) -> str:
    parts = []
    if designation:
        parts.append(designation)
    if department:
        parts.append(department)
    if not parts:
        return ""
    return f"Context: {', '.join(parts)}.\n"


def build_manager_line(manager_name: str) -> str:
    if not manager_name:
        return ""
    return f"This standup is reviewed by {manager_name}.\n"


def build_team_roster_for_person(teammates: list[dict]) -> str:
    """teammates is list of dicts with name, designation, department (excluding current speaker)."""
    if not teammates:
        return ""
    lines = []
    for t in teammates:
        parts = [x for x in [t.get("designation"), t.get("department")] if x]
        role_str = f" ({', '.join(parts)})" if parts else ""
        lines.append(f"  - {t['name']}{role_str}")
    return "Teammates:\n" + "\n".join(lines) + "\n"
