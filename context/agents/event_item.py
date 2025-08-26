from typing import Optional, List, Literal
from pydantic import BaseModel
from context.agents.base_item import BaseActionItem

class Participant(BaseModel):
    id: str  # email required by Google Calendar
    name: Optional[str] = None
    role: Optional[Literal["organizer", "attendee"]] = "attendee"
    status: Optional[Literal["accepted", "declined", "tentative", "needsAction"]] = None

class Recurrence(BaseModel):
    freq: Literal["daily", "weekly", "monthly", "yearly"]
    interval: Optional[int] = 1
    by_day: Optional[List[str]] = None
    by_month_day: Optional[List[int]] = None
    until: Optional[str] = None
    count: Optional[int] = None

class Reminder(BaseModel):
    method: Literal["popup", "email"] = "popup"
    minutes: int

class EventItem(BaseActionItem):
    item_type: Literal["event"] = "event"

    # For timed events
    datetime: Optional[str] = None         # ISO8601 start with timezone
    end_datetime: Optional[str] = None     # ISO8601 end with timezone
    timezone: Optional[str] = None

    # For all-day events
    date: Optional[str] = None             # YYYY-MM-DD (start)
    end_date: Optional[str] = None         # YYYY-MM-DD (exclusive end)

    all_day: Optional[bool] = False
    location: Optional[str] = None
    participants: Optional[List[Participant]] = None
    recurrence: Optional[Recurrence] = None
    reminders: Optional[List[Reminder]] = None
