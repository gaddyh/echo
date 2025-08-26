from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from enum import Enum
from pydantic import Field
from typing import Literal

class Repeat(str, Enum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"

class ScheduledEvent(BaseModel):
    id: Optional[str] = Field(None, description="Unique identifier (auto-generated). Do not provide.")
    user_id: Optional[str] = Field(None, description="User ID (internal use only). Do not provide.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Time the event was created. auto-generated.")

    text: str = Field(..., description="Short description of the event, like 'Doctor appointment' or 'Pick up kids'.")
    description: Optional[str] = Field(None, description="Additional context or notes about the event.")
    target_time: datetime = Field(..., description="Exact date and time the event is scheduled to happen (ISO format).")

    repeats: Repeat = Field(Repeat.NONE, description="Repetition rule. Options: none, daily, weekly, monthly, yearly.")
    location: Optional[str] = Field(None, description="Location of the event, if relevant (e.g. 'Clinic' or 'Zoom').")

    nudge_minutes_before: Optional[int] = Field(None, description="How many minutes before the event to send a reminder. If None, no nudge is sent.")

    followup_minutes_after: Optional[int] = Field(120, description="How many minutes after the event to ask the follow-up question. If None, no follow-up is scheduled.")
    followup_question: Optional[str] = Field(None, description="Question to ask the user after the event (e.g., 'Did you attend?').")