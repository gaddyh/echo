from dataclasses import dataclass
from typing import Any
from context.primitives.sender import SenderInfo, SharedContactInfo
from context.primitives.replies_info import ContentInfo
from enum import Enum
from pydantic import BaseModel
from typing import Optional
import os
from context.primitives.media import MediaInfo

class MessageDirection(str, Enum):
    INCOMING = "incoming"  # Someone else sent it
    OUTGOING = "outgoing"  # You sent it
    SELF = "self"          # You to yourself
    ECHO = "echo"          # You to yourself
    UNKOWN = "unknown"     # Unknown direction

@dataclass
class RawMessage:
    sender: SenderInfo
    content: ContentInfo
    chat_id: str
    direction: MessageDirection
    message_data: Any

class BotIdentity(BaseModel):
    phone_number: str
    whatsapp_id: str
    pushname: Optional[str]

class Media(BaseModel):
    mimetype: str
    filename: Optional[str] = None
    data: str

#wwebjs input format
class WhatsAppMessage(BaseModel):
    bot_identity: Optional[BotIdentity] = None
    chat_id: str
    chat_name: str
    is_group: bool
    is_self_group: bool
    sender: str
    message: str
    timestamp: int
    from_me: bool
    author: Optional[str] = None
    media: Optional[Media] = None


@dataclass
class SenderInfo:
    phone: Optional[str]
    name: Optional[str]
    chatId: Optional[str]
    isSelfSender: bool

@dataclass
class MediaInfo1:
    filename: Optional[str]
    mimetype: Optional[str]
    data: Optional[str] = None  # for base64 audio

@dataclass
class LocationInfo:
    latitude: float
    longitude: float

@dataclass
class ButtonReplyInfo:
    payload: str
    text: str

@dataclass
class ContentInfo:
    type: str
    text: Optional[str] = None
    media: Optional[MediaInfo] = None
    location: Optional[LocationInfo] = None
    button_reply: Optional[ButtonReplyInfo] = None
    contact: Optional[SharedContactInfo] = None

@dataclass
class Identity:
    phone: Optional[str]
    name: Optional[str]
    chatId: Optional[str]
    isSelfSender: bool

@dataclass
class MessageContext:
    webhook_uid: Optional[str]
    messageDirection: MessageDirection
    sender: SenderInfo
    content: ContentInfo
    messageData: Any
    chatName: Optional[str] 
    isGroup: bool
    isSelfGroup: bool

bot_registry = {"972546610653": "http://localhost:3000"}
    