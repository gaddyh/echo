# adapters/whatsapp/dialog360/webhook.py

from fastapi import APIRouter, Request, Header, HTTPException

from adapters.whatsapp.dialog360.adapter import Dialog360Adapter

dialog360_router = APIRouter()

adapter = Dialog360Adapter()


@dialog360_router.post("/webhook/whatsapp")
async def whatsapp_webhook(
    request: Request,
    authorization: str | None = Header(default=None),
):
    # auth check here
    body = await request.json()

    whatsapp_message = await adapter.parse_incoming(body)
    if not whatsapp_message:
        return {"status": "ignored"}

    await adapter.send_message_360dialog(
        whatsapp_message.sender.phone,
        "חושב רגע..."
    )

    return {"status": "received"}