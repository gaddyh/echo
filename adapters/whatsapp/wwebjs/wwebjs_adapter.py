import os
import base64
import tempfile
from typing import Optional
from fastapi import HTTPException
import httpx
import asyncio
from adapters.whatsapp.cloudapi.cloud_api_adapter import CloudAPIAdapter

from context.primitives.login import LoginResponse
from context.message.raw_message import (
    ContentInfo,
    SenderInfo,
    MediaInfo,
    MessageContext,
    WhatsAppMessage,
    MessageDirection
)
from shared.user import get_node_url

APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")

adapter = CloudAPIAdapter()

def get_bearer_headers():
    return {
        "Authorization": f"Bearer {APP_SECRET}"
    }

import asyncio
import httpx
from typing import Optional

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1  # initial delay (will double each retry)

async def send_message_to_bot(
    message: str,
    user_id: str,
    chat_id: str = '972552534936@c.us'
) -> dict:
    node_url = get_node_url(user_id)
    if not node_url:
        return {
            "status": "error",
            "reason": "no_node",
            "message": f"No bot node registered for user {user_id}"
        }

    url = f"{node_url}/send-message"
    payload = {"chat_id": chat_id, "message": message, "user_id": user_id}

    async with httpx.AsyncClient() as client:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = await client.post(url, json=payload, headers=get_bearer_headers())
                r.raise_for_status()
                return {
                    "status": "ok",
                    "message": r.json()
                }

            except httpx.HTTPStatusError as e:
                if 500 <= e.response.status_code < 600 and attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY_SECONDS * (2 ** (attempt - 1)))
                    continue
                return {
                    "status": "bot_error",
                    "http_status": e.response.status_code,
                    "message": e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else e.response.text
                }

            except httpx.RequestError as e:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY_SECONDS * (2 ** (attempt - 1)))
                    continue
                return {
                    "status": "network_error",
                    "reason": str(e)
                }

async def send_message_from_bot(text: str, user_id: str):
    try:
        print("Sending notification to", user_id, "with text:", text)
        await adapter.send_message_360dialog(user_id, text)
        return True
    except Exception as e:
        print(f"❌ Failed to send notification: {e}")
        return False

async def send_message_from_me(recipient_chat_id: str, text: str, user_id: str):
    print("Sending notification to", recipient_chat_id, "with text:", text)
    result = await send_message_to_bot(text, user_id, recipient_chat_id)

    if result["status"] == "ok":
        return True

    if result["status"] == "bot_error":
        msg = result["message"]
        # Handle the specific case
        if isinstance(msg, dict) and msg.get("error") == "Client not connected":
            print("⚠️ Client not connected — user needs to re-scan QR.")
            #TODO send notice to user
            return "client_not_connected"

    print(f"❌ Failed to send notification: {result}")
    return False

async def get_chat_history(chat_id: str, user_id: str, limit: int = 100):
    node_url = get_node_url(user_id)
    if not node_url:
        return {
            "status": "error",
            "reason": "no_node",
            "message": f"No bot node registered for user {user_id}"
        }

    url = f"{node_url}/chat-history/{user_id}/{chat_id}?limit={limit}"

    print("get_chat_history: ", url)
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, headers=get_bearer_headers())
            r.raise_for_status()
            print("Chat history status:", r.status_code, r.json())
            return r.json()
        except httpx.HTTPStatusError as e:
            print("Chat history error:", e.response.status_code, e.response.text)
            return {
                "status": "bot_error",
                "http_status": e.response.status_code,
                "message": e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else e.response.text
            }
        except httpx.RequestError as e:
            print("Chat history error:", e.response.status_code, e.response.text)
            return {
                "status": "network_error",
                "reason": str(e)
            }


async def start_login(user_id: str):
    node_url = get_node_url(user_id)
    if not node_url:
        return {
            "status": "error",
            "reason": "no_node",
            "message": f"No bot node registered for user {user_id}"
        }

    start_url = f"{node_url}/start-login"
    qr_url = f"{node_url}/qr/{user_id}"
    payload = {"user_id": user_id}

    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(start_url, json=payload, headers=get_bearer_headers())
            r.raise_for_status()
        except httpx.RequestError as e:
            print("Start login error:", e.response.status_code, e.response.text)
            return {
                "status": "network_error",
                "reason": str(e)
            }
        except httpx.HTTPStatusError as e:
            print("Start login error:", e.response.status_code, e.response.text)
            return {
                "status": "bot_error",
                "http_status": e.response.status_code,
                "message": e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else e.response.text
            }

        # Poll QR endpoint
        for _ in range(30):  # ~60 seconds
            try:
                qr_res = await client.get(qr_url, headers=get_bearer_headers())
                qr_res.raise_for_status()
                data = qr_res.json()

                if data.get("status") == "ready":
                    return LoginResponse(qr_image_base64=data.get("qr", ""), status="ready")

                if data.get("qr"):
                    return LoginResponse(qr_image_base64=data["qr"], status="pending")

            except Exception:
                print("Start login error:", e.response.status_code, e.response.text)
                pass

            await asyncio.sleep(2)

        return {
            "status": "timeout",
            "reason": "Login timeout"
        }


def init_message_context(data: WhatsAppMessage) -> MessageContext:
    direction = MessageDirection.INCOMING

    return MessageContext(
        bot_identity=data.bot_identity,
        webhook_uid=None,
        messageDirection=direction,
        chatName=data.chat_name,
        isGroup=data.is_group,
        isSelfGroup=data.is_self_group,
        sender=SenderInfo(
            phone=data.chat_id.split("@")[0],
            name=data.sender,
            chatId=data.chat_id,
            isSelfSender=data.from_me
        ),
        content=ContentInfo(
            type="audio" if data.media and data.media.mimetype.startswith("audio/") else "text",
            text=data.message or None,
            media=MediaInfo(
                filename=data.media.filename if data.media else None,
                mimetype=data.media.mimetype if data.media else None,
                data=data.media.data if data.media else None
            ) if data.media else None
        ),
        messageData=data.model_dump()
    )


def save_audio_base64_to_file(media: MediaInfo) -> Optional[str]:
    if not media or not media.data:
        return None

    ext = "ogg" if media.mimetype and "ogg" in media.mimetype else "bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}", dir="./tmp_audio") as f:
        f.write(base64.b64decode(media.data))
        return f.name

async def get_status():
    node_url = get_node_url("")
    if not node_url:
        return {
            "status": "error",
            "reason": "no_node",
            "message": f"No bot node registered for user {user_id}"
        }

    url = f"{node_url}/status"

    print("get_status: ", url)
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, headers=get_bearer_headers())
            r.raise_for_status()
            print("get_status status:", r.status_code, r.json())
            return r.json()
        except httpx.HTTPStatusError as e:
            print("get_status error:", e.response.status_code, e.response.text)
            return {
                "status": "bot_error",
                "http_status": e.response.status_code,
                "message": e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else e.response.text
            }
        except httpx.RequestError as e:
            print("get_status error:", e.response.status_code, e.response.text)
            return {
                "status": "network_error",
                "reason": str(e)
            }