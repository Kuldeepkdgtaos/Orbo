import logging
from typing import Optional

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 85


def attribute_speaker(speaker_label: str, participants: list[dict]) -> tuple[Optional[str], bool]:
    """Returns (participant_id, is_fuzzy_match). participant_id is None if unattributed."""
    if not participants:
        return None, False

    display_names = {p["teams_display_name"]: p["id"] for p in participants}

    # Exact match
    if speaker_label in display_names:
        return display_names[speaker_label], False

    # Fuzzy match
    result = process.extractOne(speaker_label, display_names.keys(), scorer=fuzz.WRatio)
    if result and result[1] >= FUZZY_THRESHOLD:
        matched_name = result[0]
        logger.info(
            "Fuzzy speaker attribution",
            extra={"speaker": speaker_label, "matched": matched_name, "score": result[1]},
        )
        return display_names[matched_name], True

    logger.warning(
        "Speaker unattributed",
        extra={"speaker": speaker_label},
    )
    return None, False
