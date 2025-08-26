from dataclasses import dataclass
from typing import Optional
from context.primitives.media import MediaInfo
from context.primitives.location import LocationInfo
from context.primitives.sender import SharedContactInfo, ReferralInfo

@dataclass
class ButtonReplyInfo:
    payload: str
    text: str

@dataclass
class ReplyContextInfo:
    quoted_message_id: Optional[str]
    quoted_sender_phone: Optional[str]

@dataclass
class ListReplyInfo:
    payload: str
    title: str
    description: Optional[str] = None

@dataclass
class ContentInfo:
    type: str
    text: Optional[str] = None
    media: Optional[MediaInfo] = None
    location: Optional[LocationInfo] = None
    button_reply: Optional[ButtonReplyInfo] = None
    list_reply: Optional[ListReplyInfo] = None
    reply_context: Optional[ReplyContextInfo] = None
    contact: Optional[SharedContactInfo] = None
    referral: Optional[ReferralInfo] = None