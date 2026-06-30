# adapters/whatsapp/360dialog/adapter.py

import asyncio
import base64
import logging
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from adapters.whatsapp.whatsapp_adapter import WhatsAppAdapter
from context.message.raw_message import MessageDirection, RawMessage
from context.primitives.location import LocationInfo
from context.primitives.media import MediaInfo
from context.primitives.replies_info import (
    ButtonReplyInfo,
    ContentInfo,
    ListReplyInfo,
    ReplyContextInfo,
)
from context.primitives.sender import ReferralInfo, SenderInfo, SharedContactInfo

logger = logging.getLogger(__name__)


class Dialog360Adapter(WhatsAppAdapter):
    """
    Pure 360dialog adapter.

    Required env:
        D360_API_KEY=<360dialog phone-number API key>

    No Meta Graph token.
    No WHATSAPP_PHONE_NUMBER_ID.
    No graph.facebook.com calls.
    """

    API_BASE_URL = "https://waba-v2.360dialog.io"
    MESSAGES_URL = f"{API_BASE_URL}/messages"
    MEDIA_URL = f"{API_BASE_URL}/media"

    def __init__(self) -> None:
        self.api_key = os.getenv("D360_API_KEY")
        if not self.api_key:
            raise ValueError("Missing required environment variable: D360_API_KEY")

    @property
    def headers_json(self) -> dict[str, str]:
        return {
            "D360-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

    @property
    def headers_auth(self) -> dict[str, str]:
        return {
            "D360-API-KEY": self.api_key,
        }

    # ---------------------------------------------------------------------
    # Incoming webhook parsing
    # ---------------------------------------------------------------------

    async def parse_incoming(self, data: dict[str, Any]) -> Optional[RawMessage]:
        """
        Parse a 360dialog / WhatsApp Cloud API-style webhook payload into RawMessage.

        Incoming user messages arrive under:
            entry[].changes[].value.messages[]

        Status updates arrive under:
            entry[].changes[].value.statuses[]
        """
        try:
            direction = self.detect_direction(data)
            if direction != MessageDirection.INCOMING:
                return None

            return await self.init_message_context(direction, data)

        except Exception:
            logger.exception("Error parsing incoming 360dialog webhook")
            return None

    def detect_direction(self, data: dict[str, Any]) -> MessageDirection:
        try:
            value = self._first_change_value(data)

            if value.get("messages"):
                return MessageDirection.INCOMING

            if value.get("statuses"):
                return MessageDirection.OUTGOING

            # Keeping your existing enum spelling, if it is really UNKOWN.
            return MessageDirection.UNKOWN

        except Exception:
            return MessageDirection.UNKOWN

    async def init_message_context(
        self,
        message_direction: MessageDirection,
        data: dict[str, Any],
    ) -> RawMessage:
        value = self._first_change_value(data)

        messages = value.get("messages") or []
        if not messages:
            raise ValueError("Webhook contains no messages")

        message = messages[0]

        contacts = value.get("contacts") or []
        contact = contacts[0] if contacts else {}

        sender_phone = (
            contact.get("wa_id")
            or message.get("from")
            or ""
        )

        sender_name = (
            contact.get("profile", {}).get("name")
            or ""
        )

        sender = SenderInfo(
            phone=sender_phone,
            name=sender_name,
            chatId=sender_phone,
            isSelfSender=False,
        )

        msg_type = message.get("type")
        content = ContentInfo(type=msg_type)

        if msg_type == "text":
            content.text = message.get("text", {}).get("body", "")

        elif msg_type in {"image", "video", "audio", "document"}:
            media = message.get(msg_type) or {}
            media_id = media.get("id")

            content.media = MediaInfo(
                url=f"{self.API_BASE_URL}/{media_id}" if media_id else None,
                mime_type=media.get("mime_type"),
                caption=media.get("caption"),
                sha256=media.get("sha256"),
                media_id=media_id,
            )

            # Some media messages may have captions; useful fallback.
            if media.get("caption"):
                content.text = media.get("caption")

        elif msg_type == "location":
            loc = message.get("location") or {}
            content.location = LocationInfo(
                latitude=float(loc.get("latitude") or 0.0),
                longitude=float(loc.get("longitude") or 0.0),
                name=loc.get("name"),
                address=loc.get("address"),
            )

        elif msg_type == "interactive":
            interactive = message.get("interactive") or {}
            interactive_type = interactive.get("type")

            if interactive_type == "button_reply":
                btn = interactive.get("button_reply") or {}
                content.button_reply = ButtonReplyInfo(
                    payload=btn.get("id"),
                    text=btn.get("title"),
                )
                content.text = btn.get("title") or btn.get("id")

            elif interactive_type == "list_reply":
                lst = interactive.get("list_reply") or {}
                content.list_reply = ListReplyInfo(
                    payload=lst.get("id"),
                    title=lst.get("title"),
                    description=lst.get("description"),
                )
                content.text = lst.get("title") or lst.get("id")

            else:
                logger.warning("Unhandled interactive type: %s", interactive_type)
                return None

        elif msg_type == "contacts":
            shared_contacts = message.get("contacts") or []
            first = shared_contacts[0] if shared_contacts else {}

            name_obj = first.get("name") or {}
            formatted_name = name_obj.get("formatted_name") or " ".join(
                filter(None, [name_obj.get("first_name"), name_obj.get("last_name")])
            )

            phones = first.get("phones") or []
            primary_phone = None

            for phone_obj in phones:
                if not isinstance(phone_obj, dict):
                    continue

                if phone_obj.get("wa_id"):
                    primary_phone = str(phone_obj["wa_id"]).strip()
                    break

                if not primary_phone and phone_obj.get("phone"):
                    primary_phone = str(phone_obj["phone"]).strip()

            content.contact = SharedContactInfo(
                formatted_name=formatted_name or "",
                first_name=name_obj.get("first_name"),
                last_name=name_obj.get("last_name"),
                phone=primary_phone,
            )

            if formatted_name or primary_phone:
                content.text = f"{formatted_name} ({primary_phone})"

        elif msg_type == "sticker":
            logger.info("Sticker message received; currently unsupported")
            return None

        else:
            logger.warning("Unhandled WhatsApp message type: %s", msg_type)
            return None

        if "context" in message:
            context = message["context"] or {}
            content.reply_context = ReplyContextInfo(
                quoted_message_id=context.get("id"),
                quoted_sender_phone=context.get("from"),
            )

        if "referral" in message:
            ref = message["referral"] or {}
            content.referral = ReferralInfo(
                source_url=ref.get("source_url"),
                source_type=ref.get("source_type"),
                headline=ref.get("headline"),
                body=ref.get("body"),
                image_url=ref.get("image_url"),
            )

        return RawMessage(
            sender=sender,
            content=content,
            chat_id=sender_phone,
            direction=message_direction,
            message_data=message,
        )

    # ---------------------------------------------------------------------
    # Sending messages
    # ---------------------------------------------------------------------

    async def send_message_360dialog(self, recipient: str, message: str) -> dict[str, Any]:
        """
        Compatibility method for your existing webhook code.
        """
        return await self.send_text(recipient=recipient, text=message)

    async def send_message(self, recipient: str, message: str) -> dict[str, Any]:
        """
        Generic adapter method.
        Kept as an alias so old call sites still work.
        """
        return await self.send_text(recipient=recipient, text=message)

    async def send_text(self, recipient: str, text: str) -> dict[str, Any]:
        recipient = self._normalize_phone(recipient)

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {
                "body": text,
            },
        }

        return await self._post_json(self.MESSAGES_URL, payload)

    async def send_template_360dialog(
        self,
        recipient: str,
        template_name: str,
        language_code: str = "he",
        body_parameters: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Send an approved WhatsApp template.

        For a template without variables:
            body_parameters=None

        For body variables:
            body_parameters=["Gaddy", "tomorrow", "10:00"]
        """
        recipient = self._normalize_phone(recipient)

        template: dict[str, Any] = {
            "name": template_name,
            "language": {
                "code": language_code,
            },
        }

        if body_parameters:
            template["components"] = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(value)}
                        for value in body_parameters
                    ],
                }
            ]

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "template",
            "template": template,
        }

        return await self._post_json(self.MESSAGES_URL, payload)

    async def send_typing_indicator(self, incoming_message_id: str) -> dict[str, Any]:
        """
        Current 360dialog / Cloud API typing indicator pattern.

        This is NOT recipient-based.
        It uses the incoming WhatsApp message id and marks it as read.
        """
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": incoming_message_id,
            "typing_indicator": {
                "type": "text",
            },
        }

        return await self._post_json(self.MESSAGES_URL, payload)

    async def mark_as_read(self, incoming_message_id: str) -> dict[str, Any]:
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": incoming_message_id,
        }

        return await self._post_json(self.MESSAGES_URL, payload)

    # ---------------------------------------------------------------------
    # Sending media
    # ---------------------------------------------------------------------

    async def send_image_base64(
        self,
        recipient: str,
        image_base64: str,
        filename: str = "image.png",
        caption: Optional[str] = None,
    ) -> dict[str, Any]:
        image_bytes = base64.b64decode(image_base64)

        media_id = await self.upload_media_bytes(
            file_bytes=image_bytes,
            filename=filename,
            mime_type="image/png",
        )

        if not media_id:
            return {"status": "failed", "error": "Media upload failed"}

        return await self.send_media_by_id(
            recipient=recipient,
            media_type="image",
            media_id=media_id,
            caption=caption,
        )

    async def send_media_by_id(
        self,
        recipient: str,
        media_type: str,
        media_id: str,
        caption: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        media_type: image | video | audio | document
        """
        if media_type not in {"image", "video", "audio", "document"}:
            raise ValueError("media_type must be image, video, audio, or document")

        recipient = self._normalize_phone(recipient)

        media_payload: dict[str, Any] = {"id": media_id}

        if caption and media_type in {"image", "video", "document"}:
            media_payload["caption"] = caption

        if filename and media_type == "document":
            media_payload["filename"] = filename

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": media_type,
            media_type: media_payload,
        }

        return await self._post_json(self.MESSAGES_URL, payload)

    async def upload_media_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: Optional[str] = None,
    ) -> Optional[str]:
        mime_type = mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        files = {
            "file": (filename, file_bytes, mime_type),
            "messaging_product": (None, "whatsapp"),
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    self.MEDIA_URL,
                    headers=self.headers_auth,
                    files=files,
                )
                response.raise_for_status()
                return response.json().get("id")

            except httpx.HTTPStatusError as e:
                logger.error(
                    "Failed to upload media: %s - %s",
                    e.response.status_code,
                    e.response.text,
                )
                return None

            except httpx.RequestError as e:
                logger.exception("HTTP request failed while uploading media")
                return None

    # ---------------------------------------------------------------------
    # Receiving/downloading media
    # ---------------------------------------------------------------------

    async def download_with_retry(
        self,
        media_id: str,
        retries: int = 2,
        delay: float = 1.0,
        suffix: str = ".ogg",
        save_dir: str = "./tmp_audio",
    ) -> Optional[str]:
        for attempt in range(retries + 1):
            file_path = await self.download_media_to_file(
                media_id=media_id,
                suffix=suffix,
                save_dir=save_dir,
            )

            if file_path:
                return file_path

            if attempt < retries:
                await asyncio.sleep(delay)

        return None

    async def download_media_to_file(
        self,
        media_id: str,
        suffix: str = ".ogg",
        save_dir: str = "./tmp_audio",
    ) -> Optional[str]:
        """
        360dialog media flow:
        1. GET https://waba-v2.360dialog.io/{media-id}
        2. Take returned URL
        3. Replace lookaside.fbsbx.com host with waba-v2.360dialog.io
        4. Download with D360-API-KEY
        """
        Path(save_dir).mkdir(parents=True, exist_ok=True)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                meta_resp = await client.get(
                    f"{self.API_BASE_URL}/{media_id}",
                    headers=self.headers_auth,
                )
                meta_resp.raise_for_status()

                original_url = meta_resp.json().get("url")
                if not original_url:
                    logger.error("No media URL returned for media_id=%s", media_id)
                    return None

                final_url = self._to_360dialog_media_url(original_url)

                file_resp = await client.get(
                    final_url,
                    headers=self.headers_auth,
                )
                file_resp.raise_for_status()

                with tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=suffix,
                    dir=save_dir,
                ) as f:
                    f.write(file_resp.content)
                    file_path = f.name

            if os.path.getsize(file_path) < 1024:
                logger.warning("Downloaded media file too small: %s", file_path)
                os.remove(file_path)
                return None

            return file_path

        except Exception as e:
            logger.exception("Failed to download media_id=%s: %s", media_id, e)
            return None

    async def delete_media(self, media_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.delete(
                    f"{self.API_BASE_URL}/{media_id}",
                    headers=self.headers_auth,
                )
                response.raise_for_status()
                return {"status": "deleted", "response": response.json()}

            except httpx.HTTPStatusError as e:
                logger.error(
                    "Failed to delete media: %s - %s",
                    e.response.status_code,
                    e.response.text,
                )
                return {"status": "failed", "error": e.response.text}

            except httpx.RequestError as e:
                logger.exception("HTTP request failed while deleting media")
                return {"status": "failed", "error": str(e)}

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------

    def get_identity(self, webhook_uid: str = "") -> dict[str, Any]:
        """
        360dialog does not require phone_number_id in the adapter.
        Keep this method only for interface compatibility.
        """
        return {
            "provider": "360dialog",
            "webhook_uid": webhook_uid,
        }

    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    url,
                    json=payload,
                    headers=self.headers_json,
                )

            except httpx.RequestError as e:
                logger.exception("HTTP request failed")
                return {"status": "failed", "error": str(e)}

        try:
            body = response.json()
        except Exception:
            body = response.text

        if response.status_code in {200, 201}:
            return {"status": "sent", "response": body}

        logger.error("360dialog request failed: %s - %s", response.status_code, body)
        return {
            "status": "failed",
            "status_code": response.status_code,
            "error": body,
        }

    @staticmethod
    def _normalize_phone(recipient: str) -> str:
        return (
            recipient
            .replace("@c.us", "")
            .replace("+", "")
            .replace(" ", "")
            .replace("-", "")
            .strip()
        )

    @staticmethod
    def _first_change_value(data: dict[str, Any]) -> dict[str, Any]:
        entries = data.get("entry") or []
        if not entries:
            raise ValueError("Webhook contains no entry")

        changes = entries[0].get("changes") or []
        if not changes:
            raise ValueError("Webhook contains no changes")

        return changes[0].get("value") or {}

    @staticmethod
    def _to_360dialog_media_url(original_url: str) -> str:
        parsed = urlparse(original_url)
        path_and_query = parsed.path

        if parsed.query:
            path_and_query += f"?{parsed.query}"

        return f"https://waba-v2.360dialog.io{path_and_query}"