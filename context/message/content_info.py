
from pydantic import BaseModel
from typing import Optional
from context.primitives.media import Media
from context.message.identity import BotIdentity


#wwebjs input format
class WhatsAppMessage(BaseModel):
    bot_identity: BotIdentity
    chat_id: str
    chat_name: str
    is_group: bool
    is_self_group: bool
    sender: str
    message: str
    timestamp: int
    from_me: bool
    media: Optional[Media] = None