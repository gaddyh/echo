from context.agents.base_item import BaseActionItem
from typing import Literal

class ReminderItem(BaseActionItem):
    item_type: Literal["reminder"] = "reminder"
    datetime: str  # when the reminder should trigger
