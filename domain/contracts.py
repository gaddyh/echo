from __future__ import annotations

from typing import List, Optional, Annotated, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class ActionItemSummary(BaseModel):
    id: str = Field(..., description="Unique ID of the ActionItem.")
    action: str = Field(..., description="Short description of the action (e.g., 'Dinner with Sarah').")
    action_type: str = Field(..., description="Type of the action: 'event', 'reminder', 'task', 'message', or 'other'.")
    time: Optional[datetime] = Field(None, description="Datetime of the ActionItem, or null if not set.")
    participants: List[str] = Field(default_factory=list, description="List of participant names.")
    location: Optional[str] = Field(None, description="Location if specified, else null.")


class ScheduledMessageItem(BaseModel):
    item_id: str
    command: Literal["create", "update", "delete"]
    item_type: Literal["message"] = "message"
    message: str
    scheduled_time: str  # ISO8601
    recipient_name: str
    recipient_chat_id: Annotated[str, Field(pattern=r".+@(c|g)\.us")]
    status: Optional[str] = None
