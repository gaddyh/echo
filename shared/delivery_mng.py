from pydantic import BaseModel
from datetime import datetime

class SendingStatus(BaseModel):
    item_type: str        # "action_item" or "scheduled_message"
    item_id: str          # foreign key to the item
    user_id: str          # owner
    retry_count: int = 0
    last_status: str = "pending"   # pending, sending, failed, completed, failed_echo
    last_attempt: datetime | None = None
    last_error: str | None = None
