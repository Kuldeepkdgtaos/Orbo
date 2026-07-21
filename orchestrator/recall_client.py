import logging
from typing import Any

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)

RECALL_BASE_URL = f"https://{settings.recall_region}.recall.ai/api/v1"


class RecallClient:
    def __init__(self):
        self.headers = {
            "Authorization": f"Token {settings.recall_api_key}",
            "Content-Type": "application/json",
        }

    async def create_bot(self, meeting_url: str, webhook_url: str, bot_name: str = "AI Standup Manager") -> dict[str, Any]:
        payload = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            "webhook_url": webhook_url,
            # recallai_streaming sends transcript.data webhook events in real-time
            "recording_config": {
                "transcript": {
                    "provider": {
                        "recallai_streaming": {}
                    }
                }
            },
            # Also configure real-time destination so transcript events reach our webhook
            "real_time_transcription": {
                "destination_url": webhook_url,
                "partial_results": False,
            },
            "automatic_leave": {
                "waiting_room_timeout": 300,
                "noone_joined_timeout": 120,
                "in_call_timeout": 1800,
            },
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{RECALL_BASE_URL}/bot",
                headers=self.headers,
                json=payload,
            )
            if not resp.is_success:
                logger.error("Recall create_bot failed", extra={"status": resp.status_code, "body": resp.text})
                # If real_time_transcription is rejected, retry without it
                if resp.status_code == 400 and "real_time_transcription" in resp.text:
                    logger.warning("Retrying without real_time_transcription")
                    payload.pop("real_time_transcription", None)
                    resp = await client.post(
                        f"{RECALL_BASE_URL}/bot",
                        headers=self.headers,
                        json=payload,
                    )
            resp.raise_for_status()
            return resp.json()

    async def leave_bot(self, bot_id: str) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{RECALL_BASE_URL}/bot/{bot_id}/leave_call",
                headers=self.headers,
            )
            resp.raise_for_status()

    async def get_bot(self, bot_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{RECALL_BASE_URL}/bot/{bot_id}",
                headers=self.headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_transcript(self, bot_id: str, transcript_id: str | None = None) -> list[dict[str, Any]]:
        """
        Fetch transcript using Recall.ai's current API.
        - If transcript_id is given (from transcript.done event), use the new /transcript/{id} endpoint first.
        - Falls back to scanning bot.recordings for transcript data.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:

            # Step 0: Try new transcript endpoint with transcript_id if available
            if transcript_id:
                for url in [
                    f"{RECALL_BASE_URL}/transcript/{transcript_id}/",
                    f"{RECALL_BASE_URL}/transcript/{transcript_id}",
                ]:
                    t_resp = await client.get(url, headers=self.headers)
                    if t_resp.is_success:
                        data = t_resp.json()
                        logger.info("Transcript via new endpoint", extra={"url": url, "preview": str(data)[:300]})

                        # Transcript data is a download_url pointing to S3 — fetch it
                        download_url = (data.get("data") or {}).get("download_url")
                        if download_url:
                            dl_resp = await client.get(download_url)
                            if dl_resp.is_success:
                                downloaded = dl_resp.json()
                                logger.info("Downloaded transcript", extra={"preview": str(downloaded)[:300]})
                                result = self._parse_transcript(downloaded)
                                if result:
                                    return result

                        result = self._parse_transcript(data)
                        if result:
                            return result

            # Step 1: Get full bot details — transcript is inside recordings[]
            bot_resp = await client.get(
                f"{RECALL_BASE_URL}/bot/{bot_id}",
                headers=self.headers,
            )
            if not bot_resp.is_success:
                logger.error("Failed to get bot details", extra={"status": bot_resp.status_code})
                return []

            bot_data = bot_resp.json()
            recordings = bot_data.get("recordings", [])
            logger.info(
                "Bot recordings",
                extra={"bot_id": bot_id, "count": len(recordings), "data": str(recordings)[:600]},
            )

            # Step 2: Look for transcript inside each recording
            all_utterances: list[dict[str, Any]] = []
            for rec in recordings:
                # Direct transcript field in recording
                if "transcript" in rec and rec["transcript"]:
                    logger.info("Found transcript in recording", extra={"rec_id": rec.get("id")})
                    all_utterances.extend(self._parse_transcript(rec["transcript"]))
                    continue

                # media_shortcuts may contain a transcript download_url
                shortcuts = rec.get("media_shortcuts", {}) or {}
                for shortcut_key in ("transcript", "transcript_v2"):
                    transcript_info = shortcuts.get(shortcut_key, {}) or {}
                    # Could be direct download_url or nested under data.download_url
                    download_url = (
                        transcript_info.get("download_url")
                        or (transcript_info.get("data") or {}).get("download_url")
                    )
                    if download_url:
                        dl_resp = await client.get(download_url)
                        if dl_resp.is_success:
                            logger.info("Transcript from media_shortcuts download", extra={"key": shortcut_key})
                            result = self._parse_transcript(dl_resp.json())
                            if result:
                                all_utterances.extend(result)
                                break

                # Try transcript endpoint using recording id
                rec_id = rec.get("id")
                if rec_id:
                    for endpoint in [
                        f"{RECALL_BASE_URL}/recording/{rec_id}/transcript",
                        f"{RECALL_BASE_URL}/bot/{bot_id}/recording/{rec_id}/transcript",
                    ]:
                        t_resp = await client.get(endpoint, headers=self.headers)
                        if t_resp.is_success:
                            logger.info("Transcript from recording endpoint", extra={"endpoint": endpoint})
                            all_utterances.extend(self._parse_transcript(t_resp.json()))
                            break

            if all_utterances:
                return all_utterances

            logger.error(
                "Could not find transcript anywhere",
                extra={"bot_id": bot_id, "recording_keys": [list(r.keys()) for r in recordings]},
            )
            return []

    @staticmethod
    def _parse_transcript(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("results", "transcript", "captions", "data", "utterances"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []

    async def send_chat_message(self, bot_id: str, message: str) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{RECALL_BASE_URL}/bot/{bot_id}/send_chat_message",
                headers=self.headers,
                json={"message": message},
            )
            if not resp.is_success:
                logger.error("send_chat_message failed", extra={"bot_id": bot_id, "status": resp.status_code, "body": resp.text})
            resp.raise_for_status()


recall_client = RecallClient()
