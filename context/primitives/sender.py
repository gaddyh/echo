from dataclasses import dataclass
from typing import Optional

@dataclass
class SenderInfo:
    phone: Optional[str]
    name: Optional[str]
    chatId: Optional[str]
    isSelfSender: bool

@dataclass
class SharedContactInfo:
    formatted_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None

@dataclass
class ReferralInfo:
    source_url: str
    source_type: str
    headline: Optional[str] = None
    body: Optional[str] = None
    image_url: Optional[str] = None
