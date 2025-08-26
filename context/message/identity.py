from pydantic import BaseModel
from typing import Optional

class BotIdentity(BaseModel):
    phone_number: str
    whatsapp_id: str
    pushname: Optional[str]