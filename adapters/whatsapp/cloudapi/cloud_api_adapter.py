import os
import logging
import httpx
from dotenv import load_dotenv
from adapters.whatsapp.whatsapp_adapter import WhatsAppAdapter
from context.primitives.sender import SenderInfo
from context.primitives.replies_info import ContentInfo, ButtonReplyInfo, ListReplyInfo, ReplyContextInfo
from context.primitives.location import LocationInfo
from context.primitives.sender import SharedContactInfo, ReferralInfo
from context.primitives.media import MediaInfo
from context.message.raw_message import RawMessage, MessageDirection
from typing import Optional
import base64
import tempfile
from typing import Optional

load_dotenv(".venv/.env")

logger = logging.getLogger(__name__)

class CloudAPIAdapter(WhatsAppAdapter):
    def __init__(self):
        self.phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        self.access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")
        self.api_key = os.getenv("D360_API_KEY")
        self.base_url = "https://waba-v2.360dialog.io/messages"  # ✅ add this

    async def parse_incoming(self, data: dict) -> Optional[RawMessage]:
        try:
            entries = data.get("entry", [])
            if not entries:
                return None

            changes = entries[0].get("changes", [])
            if not changes:
                return None

            message_direction = self.detect_direction(data)
            if message_direction != MessageDirection.INCOMING:
                return None

            # NEW: prevent loopback by ignoring messages from own bot
            value = changes[0].get("value", {})
            messages = value.get("messages", [])
            if messages:
                from_user = messages[0].get("from")
                logger.debug(f"From user: {from_user} | Self phone ID: {self.phone_number_id}")
                my_phone = value.get("metadata", {}).get("display_phone_number")
                if from_user == my_phone:
                    logger.info("Ignoring message from self (loopback)")
                    return None

            return await self.init_message_context(message_direction, data)

        except Exception as e:
            logger.exception("Error parsing incoming CloudAPI message")
            return None

    async def send_message_360dialog(self, recipient: str, message: str) -> dict:
        logger.info(f"📤 Sending message to {recipient} | text: {message}")

        url = "https://waba-v2.360dialog.io/messages"  # 360dialog endpoint
        headers = {
            "D360-API-KEY": self.api_key,  # 360dialog uses this header instead of Bearer token
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",  # ✅ REQUIRED
            "to": recipient,
            "type": "text",
            "text": {
                "body": message
            }
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
            except httpx.RequestError as e:
                logger.exception("🌐 HTTPX request failed")
                return {"status": "failed", "error": str(e)}

        if response.status_code == 200:
            logger.debug("✅ Message sent successfully")
            return {"status": "sent", "response": response.json()}
        else:
            logger.error(f"❌ Failed to send message: {response.status_code} - {response.text}")
            return {"status": "failed", "error": response.text}

    async def send_typing_indicator(self, recipient: str, status: str = "on") -> dict:
        """
        Send typing indicator to WhatsApp user via 360dialog.

        Args:
            recipient: WhatsApp user phone number in international format (e.g. "972501234567").
            status: "on" (typing_on) or "off" (typing_off).
        """
        if status not in ["on", "off"]:
            raise ValueError("status must be 'on' or 'off'")

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "typing",
            "typing": {"status": f"typing_{status}"}
        }

        headers = {
            "D360-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(self.base_url, json=payload, headers=headers)
                response.raise_for_status()
                logger.debug(f"✅ Typing indicator {status} sent to {recipient}")
                return {"status": "sent", "response": response.json()}
            except httpx.HTTPStatusError as e:
                logger.error(f"❌ Failed typing indicator: {e.response.status_code} - {e.response.text}")
                return {"status": "failed", "error": e.response.text}
            except httpx.RequestError as e:
                logger.exception("🌐 HTTPX request failed")
                return {"status": "failed", "error": str(e)}

    async def send_template_360dialog(self, recipient: str, template_name: str, language_code: str = "he", namespace: str = "c203d4a9_1096_4de0_9b93_db491b53c2bd") -> dict:
        logger.info(f"📤 Sending template '{template_name}' to {recipient}")

        url = "https://waba-v2.360dialog.io/messages"
        headers = {
            "D360-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "template",
            "template": {
                "namespace": namespace,
                "name": template_name,
                "language": {
                    "code": language_code,
                    "policy": "deterministic"
                },
                "components": []  # Your template has no variables
            }
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
            except httpx.RequestError as e:
                logger.exception("🌐 HTTPX request failed")
                return {"status": "failed", "error": str(e)}

        if response.status_code == 200:
            logger.debug("✅ Template sent successfully")
            return {"status": "sent", "response": response.json()}
        else:
            logger.error(f"❌ Failed to send template: {response.status_code} - {response.text}")
            return {"status": "failed", "error": response.text}

    async def send_message(self, recipient: str, message: str) -> dict:
        print("Sending message to", recipient, "with message:", message)
        url = f"https://graph.facebook.com/v16.0/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient.replace("@c.us", ""),
            "type": "text",
            "text": {"body": message}
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            return {"status": "sent", "response": response.json()}
        else:
            logger.error(f"Failed to send message: {response.status_code} - {response.text}")
            return {"status": "failed", "error": response.text}

    async def send_template_message(self, recipient: str, parameters: list[str], template_name: str="scheduled_message1", language_code: str="he") -> dict:
        print("Sending template message to", recipient, "with template:", template_name)
        print("Parameters:", parameters)
        url = f"https://graph.facebook.com/v16.0/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient.replace("@c.us", ""),
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": language_code
                },
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {
                                "type": "text",
                                "parameter_name": "recipient",
                                "text": parameters[0]
                            },
                            {
                                "type": "text",
                                "parameter_name": "sender",
                                "text": parameters[1]
                            },
                            {
                                "type": "text",
                                "parameter_name": "text",
                                "text": parameters[2]
                            }          
                        ]
                    }
                ]
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)

            if response.status_code == 200:
                return {"status": "sent", "response": response.json()}
            else:
                logger.error(f"Failed to send template message: {response.status_code} - {response.text}")
                return {"status": "failed", "error": response.text}

    def get_identity(self, webhook_uid: str) -> dict:
        return {
            "phone": self.phone_number_id
        }

    def detect_direction(self, data: dict) -> str:
        try:
            change = data.get("entry", [{}])[0].get("changes", [{}])[0]
            value = change.get("value", {})
            if "messages" in value:
                return MessageDirection.INCOMING
            if "statuses" in value:
                return MessageDirection.OUTGOING
            return MessageDirection.UNKOWN
        except Exception:
            return MessageDirection.UNKOWN

    async def init_message_context(self, message_direction: str, data: dict) -> RawMessage:
        print("init_message_context")
        try:
            change = data.get("entry", [{}])[0].get("changes", [{}])[0]
            value = change.get("value", {})
            contact = value.get("contacts", [{}])[0]
            message = value.get("messages", [{}])[0]

            sender_phone = contact.get("wa_id", "")
            sender_name = contact.get("profile", {}).get("name", "")
            chat_id = sender_phone

            sender = SenderInfo(
                phone=sender_phone,
                name=sender_name,
                chatId=chat_id,
                isSelfSender=False
            )
            print("sender", sender)

            msg_type = message.get("type")
            content = ContentInfo(type=msg_type)

            if msg_type == "text":
                content.text = message.get("text", {}).get("body", "")

            elif msg_type in ["image", "video", "audio", "document"]:
                media = message.get(msg_type, {})
                media_id = media.get("id")
                mime_type = media.get("mime_type")
                caption = media.get("caption")
                sha256 = media.get("sha256")

                # Build media download URL
                media_url = f"https://graph.facebook.com/v16.0/{media_id}"
                url = f"https://waba-v2.360dialog.io/v1/media/{media_id}"

                content.media = MediaInfo(
                    url=url,
                    mime_type=mime_type,
                    caption=caption,
                    sha256=sha256,
                    media_id=media_id
                )


            elif msg_type == "location":
                loc = message.get("location", {})
                content.location = LocationInfo(
                    latitude=float(loc.get("latitude", 0.0)),
                    longitude=float(loc.get("longitude", 0.0)),
                    name=loc.get("name"),
                    address=loc.get("address")
                )

            elif msg_type == "interactive":
                interactive = message.get("interactive", {})
                if interactive.get("type") == "button_reply":
                    btn = interactive.get("button_reply", {})
                    content.button_reply = ButtonReplyInfo(
                        payload=btn.get("id"),
                        text=btn.get("title")
                    )
                elif interactive.get("type") == "list_reply":
                    lst = interactive.get("list_reply", {})
                    content.list_reply = ListReplyInfo(
                        payload=lst.get("id"),
                        title=lst.get("title"),
                        description=lst.get("description")
                    )

            elif msg_type == "contacts":
                # 360dialog allows sharing multiple contacts.
                # For backward compatibility we take the FIRST one here.
                # (If you want multi-contact support, say the word and I’ll adjust the schema.)
                shared_contacts = message.get("contacts") or []
                first = (shared_contacts[0] if shared_contacts else {}) or {}

                name_obj = first.get("name") or {}
                formatted_name = name_obj.get("formatted_name") or (
                    " ".join(filter(None, [name_obj.get("first_name"), name_obj.get("last_name")])) or ""
                )

                phones = first.get("phones") or []
                primary_phone = None
                # Prefer wa_id (WhatsApp-normalized); else fall back to phone
                for p in phones:
                    if isinstance(p, dict):
                        if p.get("wa_id"):
                            primary_phone = str(p["wa_id"]).strip()
                            break
                        if not primary_phone and p.get("phone"):
                            primary_phone = str(p["phone"]).strip()

                content.contact = SharedContactInfo(
                    formatted_name=formatted_name,
                    first_name=name_obj.get("first_name"),
                    last_name=name_obj.get("last_name"),
                    phone=primary_phone
                )

            elif msg_type == "sticker":
                logger.info("Sticker message received — currently unsupported.")
                return None

            else:
                logger.warning(f"Unhandled message type: {msg_type}")
                return None

            # Optional: quoted reply context
            if "context" in message:
                context = message["context"]
                content.reply_context = ReplyContextInfo(
                    quoted_message_id=context.get("id"),
                    quoted_sender_phone=context.get("from")
                )

            # Optional: referral (ad attribution)
            if "referral" in message:
                ref = message["referral"]
                content.referral = ReferralInfo(
                    source_url=ref.get("source_url"),
                    source_type=ref.get("source_type"),
                    headline=ref.get("headline"),
                    body=ref.get("body"),
                    image_url=ref.get("image_url")
                )

            identity = sender
            print("identity", identity)

            return RawMessage(
                sender=sender,
                content=content,
                chat_id=chat_id,
                direction=message_direction,
                message_data=message
            )

        except Exception as e:
            logger.exception("Error building MessageState from CloudAPI data")
            raise

    async def send_image_base64(self, recipient: str, image_base64: str, filename: str = "qr.png", caption: str = None):
        # Step 1: Upload image to get media ID
        media_id = await self._upload_image(image_base64, filename)
        if not media_id:
            return {"status": "failed", "error": "Upload failed"}

        # Step 2: Send the image using media ID
        url = f"https://graph.facebook.com/v16.0/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient.replace("@c.us", ""),
            "type": "image",
            "image": {
                "id": media_id
            }
        }
        if caption:
            payload["image"]["caption"] = caption

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            return {"status": "sent", "response": response.json()}
        else:
            logger.error(f"Failed to send image: {response.status_code} - {response.text}")
            return {"status": "failed", "error": response.text}

    async def _upload_image(self, image_base64: str, filename: str) -> str:
        url = f"https://graph.facebook.com/v16.0/{self.phone_number_id}/media"
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }

        image_bytes = base64.b64decode(image_base64)
        files = {
            "file": (filename, image_bytes, "image/png"),
            "messaging_product": (None, "whatsapp")
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, files=files)

        if response.status_code == 200:
            return response.json().get("id")
        else:
            logger.error(f"Failed to upload image: {response.status_code} - {response.text}")
            return None

    async def download_with_retry(self, media_id, retries=2, delay=1):
        import asyncio
        for i in range(retries):
            file = await self.download_media_to_file(media_id)
            if file:
                return file
            await asyncio.sleep(delay)
        return None

    async def download_media_to_file(self, media_id: str, suffix: str = ".ogg", save_dir: str = "./tmp_audio") -> Optional[str]:
        import os, tempfile, httpx
        from urllib.parse import urlparse

        os.makedirs(save_dir, exist_ok=True)

        headers = {
            "D360-API-KEY": self.api_key,
            "Accept-Encoding": "gzip, deflate, br"
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Step 1: Get the signed media path
                meta_resp = await client.get(f"https://waba-v2.360dialog.io/{media_id}", headers=headers)
                meta_resp.raise_for_status()
                full_url = meta_resp.json().get("url")
                if not full_url:
                    print(f"❌ No URL returned for media_id: {media_id}")
                    return None

                # Step 2: Replace hostname
                parsed = urlparse(full_url)
                media_path = parsed.path + "?" + parsed.query
                final_url = f"https://waba-v2.360dialog.io{media_path}"

                # Step 3: Download media
                file_resp = await client.get(final_url, headers=headers)  # ✅ headers ARE required here
                file_resp.raise_for_status()

                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=save_dir) as f:
                    f.write(file_resp.content)
                    file_path = f.name

            # Step 4: Validate size
            if os.path.getsize(file_path) < 1024:
                print(f"⚠️ Media file too small: {file_path}")
                os.remove(file_path)
                return None

            return file_path

        except Exception as e:
            print(f"❌ Failed to download media for ID {media_id}: {e}")
            return None
