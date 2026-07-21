import base64
import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import HTTPException, Request

from shared.config import settings

logger = logging.getLogger(__name__)

# In-memory dedup set. Replace with DB or Redis for multi-instance.
_processed_event_ids: set[str] = set()


def verify_recall_signature(payload: bytes, headers: dict) -> bool:
    """
    Recall.ai uses Svix for webhook delivery.
    Secret format:  whsec_<base64>
    Signed content: {svix-id}.{svix-timestamp}.{raw_body}
    Signature:      base64(HMAC-SHA256(secret, signed_content))
    Header:         svix-signature: v1,<base64sig> [v1,<sig2> ...]
    """
    if not settings.recall_webhook_secret:
        logger.warning("No webhook secret configured — skipping verification")
        return True

    svix_id = headers.get("svix-id", "")
    svix_timestamp = headers.get("svix-timestamp", "")
    svix_signature = headers.get("svix-signature", "")

    if not all([svix_id, svix_timestamp, svix_signature]):
        # Headers missing — accept but warn (happens in local dev / test sends)
        logger.warning(
            "Svix headers missing — accepting without signature verification",
            extra={"svix_id": svix_id, "has_sig": bool(svix_signature)},
        )
        return True

    secret = settings.recall_webhook_secret
    if secret.startswith("whsec_"):
        secret = secret[len("whsec_"):]

    try:
        secret_bytes = base64.b64decode(secret)
    except Exception as e:
        logger.error("Cannot decode webhook secret", extra={"error": str(e)})
        return True  # Don't block on misconfiguration

    signed_content = f"{svix_id}.{svix_timestamp}.".encode() + payload
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    ).decode()

    # svix-signature may contain multiple space-separated sigs: "v1,aaa v1,bbb"
    for entry in svix_signature.split(" "):
        if "," in entry:
            _, sig_value = entry.split(",", 1)
            if hmac.compare_digest(expected, sig_value):
                return True

    logger.warning("Webhook signature mismatch")
    return False


def is_duplicate_event(event_id: str) -> bool:
    if event_id in _processed_event_ids:
        return True
    _processed_event_ids.add(event_id)
    if len(_processed_event_ids) > 10_000:
        _processed_event_ids.clear()
    return False


async def parse_and_verify_webhook(request: Request) -> dict[str, Any]:
    body = await request.body()
    # Pass all headers as a plain dict (lowercase keys from Starlette)
    if not verify_recall_signature(body, dict(request.headers)):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    return json.loads(body)
