# adapters/whatsapp/360dialog/webhook.py
from fastapi import APIRouter, Request
from adapters.whatsapp.cloudapi.cloud_api_adapter import CloudAPIAdapter
from agents.main import handleUserInput
from context.message.raw_message import RawMessage
from shared.google_tts import transcribe_opus_file, media_duration_seconds
from shared.user import get_user
import os
from agents.echo.tools.helper import try_add_chat_to_recent_chats

dialog360_router = APIRouter()

from cachetools import TTLCache
from shared.observability.metrics import track_stt_transcribed

STT_PRICE_PER_MIN_USD = float(os.getenv("STT_PRICE_PER_MIN_USD", "0.024"))  # set in prod

# Deduplication cache: max 1000 message IDs, 5-minute TTL
message_cache = TTLCache(maxsize=1000, ttl=300)
adapter = CloudAPIAdapter()

from fastapi import FastAPI, Request, Header, HTTPException

WEBHOOK_SECRET = "3ba86ffb-a96f-4ec0-8e10-d407ced76649"  # must match the one you set at 360dialog

@dialog360_router.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, authorization: str = Header(None)):
    # accept old requests without header (temporary)
    if authorization == f"Bearer {WEBHOOK_SECRET}":
        print("✅ Verified via Bearer token")
    else:
        print("⚠️ No Authorization header (old webhook request, allowed temporarily)")
        raise HTTPException(status_code=401, detail="Unauthorized")

    body = await request.json()
    print("📩 Incoming message:", body)

    # Step 1: Try to extract message ID for deduplication
    try:
        entries = body.get("entry", [])
        changes = entries[0].get("changes", []) if entries else []
        value = changes[0].get("value", {}) if changes else {}
        messages = value.get("messages", [])
        msg_id = messages[0].get("id") if messages else None
    except Exception as e:
        print("⚠️ Failed to parse message ID:", e)
        msg_id = None

    if msg_id:
        if msg_id in message_cache:
            print(f"⚠️ Duplicate message ignored (ID: {msg_id})")
            return {"status": "duplicate"}
        message_cache[msg_id] = True  # mark as processed
        print(f"💾 Message ID cached: {msg_id}")
    else:
        print("⚠️ No message ID found in webhook")

    # Step 2: Parse incoming message as usual
    try:
        whatsappMessage: RawMessage = await adapter.parse_incoming(body)
    except Exception as e:
        print("⚠️ Failed to parse incoming message:", e)
        return {"status": "ignored"}
    if not whatsappMessage:
        print("⚠️ No valid message extracted")
        return {"status": "ignored"}

    print("✅ Parsed result:")
    print("message:", whatsappMessage.content.text)
    print("phone:", whatsappMessage.sender.phone)

   # Step 3: Handle voice message (only if audio)
    if whatsappMessage.content.media and getattr(whatsappMessage.content.media, "mime_type", "").startswith("audio/"):
        filename = await adapter.download_with_retry(whatsappMessage.content.media.media_id)
        if not filename:
            # Download failed → inform user, stop
            print("❌ Audio media download failed")
            await adapter.send_message_360dialog(
                whatsappMessage.sender.phone,
                "לא הצלחתי לעבד את ההודעה הקולית. אפשר לנסות שוב?"
            )
            return {"status": "received"}

        user = get_user(whatsappMessage.sender.phone)
        if user is None:
            await adapter.send_message_360dialog(
                whatsappMessage.sender.phone,
                "תודה רבה אבל עלייך להירשם למערכת לפני שימוש ראשון. אנא הירשם בכתובת "
                f"https://inme-1.onrender.com/login?user_id={whatsappMessage.sender.phone}"
            )
            os.remove(filename)
            return {"status": "received"}

        # duration for metrics (before we delete files)
        audio_seconds = media_duration_seconds(filename)

        try:
            transcript = transcribe_opus_file(filename, list(user.runtime.recent_chats.keys()))
            whatsappMessage.content.text = "stt: " + transcript

            # ✅ metrics: STT success
            track_stt_transcribed(
                user_id=whatsappMessage.sender.phone,
                stt_model="google_cloud_speech",
                stt_seconds=audio_seconds,
                cost_usd=(audio_seconds / 60.0) * STT_PRICE_PER_MIN_USD,
                ok=1,
            )
        except Exception:
            # ❌ metrics: STT failed
            track_stt_transcribed(
                user_id=whatsappMessage.sender.phone,
                stt_model="google_cloud_speech",
                stt_seconds=audio_seconds,
                cost_usd=0.0,
                ok=0,
            )
            os.remove(filename)
            await adapter.send_message_360dialog(
                whatsappMessage.sender.phone,
                "לא הצלחתי להבין את ההודעה הקולית. אפשר לנסות שוב?"
            )
            return {"status": "received"}
        finally:
            # Only clean up file here; no messaging from finally
            if os.path.exists(filename):
                os.remove(filename)

    elif whatsappMessage.content.contact:
        contact = whatsappMessage.content.contact
        print(f"📇 Received shared contact: {contact.formatted_name} | {contact.phone}")
        try_add_chat_to_recent_chats(whatsappMessage.sender.phone, contact.phone, contact.formatted_name)
        whatsappMessage.content.text = f"text: הנה פרטי איש הקשר: {contact.formatted_name} ({contact.phone})"

    else:
        # Regular text message
        whatsappMessage.content.text = "text: " + whatsappMessage.content.text

    # Step 4: 
    # Step 1: send placeholder
    await adapter.send_message_360dialog(whatsappMessage.sender.phone, "חושב רגע...")

    result = await handleUserInput(whatsappMessage, whatsappMessage.sender.phone)
    # Step 3: send the real message
    await adapter.send_message_360dialog(whatsappMessage.sender.phone, result)

    return {"status": "received"}

