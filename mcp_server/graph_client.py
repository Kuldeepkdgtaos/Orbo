import base64
import logging
import time
from typing import Optional

import httpx
import msal

from shared.config import settings

logger = logging.getLogger(__name__)

_token_cache: dict = {"token": None, "expires_at": 0}


def _get_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    authority = f"https://login.microsoftonline.com/{settings.ms_graph_tenant_id}"
    app = msal.ConfidentialClientApplication(
        settings.ms_graph_client_id,
        authority=authority,
        client_credential=settings.ms_graph_client_secret,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Failed to get MS Graph token: {result.get('error_description')}")

    _token_cache["token"] = result["access_token"]
    _token_cache["expires_at"] = now + result.get("expires_in", 3600)
    return _token_cache["token"]


async def send_email(to_recipients: list[str], subject: str, html_body: str, attachment_bytes: bytes, attachment_name: str) -> str:
    token = _get_access_token()
    b64 = base64.b64encode(attachment_bytes).decode()

    message = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html_body},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_recipients],
            "attachments": [{
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": attachment_name,
                "contentBytes": b64,
                "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }],
        },
        "saveToSentItems": True,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"https://graph.microsoft.com/v1.0/users/{settings.ms_graph_sender_email}/sendMail",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=message,
        )
        if resp.status_code == 401:
            _token_cache["token"] = None
            token = _get_access_token()
            resp = await client.post(
                f"https://graph.microsoft.com/v1.0/users/{settings.ms_graph_sender_email}/sendMail",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=message,
            )
        resp.raise_for_status()
        return resp.headers.get("Message-ID", "sent")
