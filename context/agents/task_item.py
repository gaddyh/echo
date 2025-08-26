from context.agents.base_item import BaseActionItem
from typing import Literal, Optional

class TaskItem(BaseActionItem):
    item_type: Literal["task"] = "task"
    due: Optional[str] = None            # ISO8601 due date
    completed: Optional[bool] = False
    list_id: Optional[str] = None        # Google Tasks list ID (e.g. "My Tasks")
    parent_id: Optional[str] = None      # If set, this task is a subtask of another
    position: Optional[str] = None       # (Google uses this for ordering)
