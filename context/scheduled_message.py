from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from pydantic import Field

class ScheduledMessage(BaseModel):
    item_id: Optional[str] = Field(None, description="Unique identifier (auto-generated). Do not provide.")
    text: str = Field(..., description="The message to send. always verify with the user before sending.")
    scheduled_time: datetime = Field(..., description="Exact date and time the message is scheduled to happen (ISO format).")
    chat_id: str = Field(..., description="The chat id, the message is for. Must start with international prefix: 972546610653 and not 0546610653")
    chat_name: str = Field(..., description="The chat name, the message is for.")