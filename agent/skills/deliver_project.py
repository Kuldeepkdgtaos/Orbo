"""
deliver_project_report skill — build the Excel report and email the PROJECT
status digest to management. The delivery mechanics are identical to the
standup deliver_report (Excel + MS Graph email + audit); only the email subject
prefix differs ("Project Status" vs "Standup Summary"), so this reuses
run_deliver rather than duplicating the pipeline.
"""
from agent.skills.deliver import run_deliver


async def run_deliver_project(standup_id: str, force_resend: bool = False) -> dict:
    return await run_deliver(standup_id, force_resend=force_resend, subject_prefix="Project Status")
