# agents/main.py — DEPRECATED: logic now lives in assistant/glue.py
# This shim is kept for any callers that have not yet migrated.

from context.message.raw_message import RawMessage
from domain.inbound import InboundMessage
from infra.app.wiring import assistant, user_ctx


async def handleUserInput(rawMessage: RawMessage, user_id: str) -> str:
    inbound = InboundMessage(
        user_id=user_id,
        sender_name=rawMessage.sender.name or "",
        text=rawMessage.content.text or "",
    )
    ctx = user_ctx.get(user_id)
    return await assistant.handle(inbound, ctx)
