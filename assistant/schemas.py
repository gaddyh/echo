from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    """Tool-arg schema for process_self_action (reminder / task / event via Firestore)."""
    item_id: Optional[str] = None
    command: Literal["create", "update", "delete"]
    item_type: Literal["reminder", "task", "event"]
    title: str
    description: Optional[str] = None
    datetime: Optional[str] = None
    location: Optional[str] = None
    status: Optional[str] = None
    op_id: Optional[str] = None


class BaseActionItem(BaseModel):
    item_id: Optional[str] = None
    command: Literal["create", "update", "delete"]
    item_type: Literal["reminder", "task", "event"]
    title: str
    description: Optional[str] = None
    status: Optional[str] = None
    op_id: Optional[str] = None


class ReminderItem(BaseActionItem):
    item_type: Literal["reminder"] = "reminder"
    datetime: str  # when the reminder should trigger


class TaskItem(BaseActionItem):
    item_type: Literal["task"] = "task"
    due: Optional[str] = None
    completed: Optional[bool] = False
    list_id: Optional[str] = None
    parent_id: Optional[str] = None
    position: Optional[str] = None


class Participant(BaseModel):
    id: str
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
    datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    timezone: Optional[str] = None
    date: Optional[str] = None
    end_date: Optional[str] = None
    all_day: Optional[bool] = False
    location: Optional[str] = None
    participants: Optional[List[Participant]] = None
    recurrence: Optional[Recurrence] = None
    reminders: Optional[List[Reminder]] = None
