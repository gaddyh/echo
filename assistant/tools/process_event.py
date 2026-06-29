from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from assistant.schemas import EventItem
from shared.observability.metrics import track_tool_call
import time as pytime


def build_event_body(kwargs: dict) -> dict:
    """Builds a Google Calendar event body from EventItem kwargs. Kept for backward compat — canonical copy is in infra.services.scheduling_service."""
    body = {
        "summary": kwargs["title"],
        "description": kwargs.get("description"),
    }

    # Timed vs all-day
    if kwargs.get("all_day"):
        if not kwargs.get("date") or not kwargs.get("end_date"):
            raise ValueError("Missing date/end_date for all-day event")
        body["start"] = {"date": kwargs["date"]}
        body["end"] = {"date": kwargs["end_date"]}
    else:
        if not kwargs.get("datetime"):
            raise ValueError("Missing datetime for timed event")
        body["start"] = {
            "dateTime": kwargs["datetime"],
            "timeZone": kwargs.get("timezone", "UTC"),
        }
        body["end"] = {
            "dateTime": kwargs.get("end_datetime", kwargs["datetime"]),
            "timeZone": kwargs.get("timezone", "UTC"),
        }

    # Optional fields
    if kwargs.get("location"):
        body["location"] = kwargs["location"]

    if kwargs.get("participants"):
        body["attendees"] = [
            {"email": p.id, "responseStatus": p.status or "needsAction"}
            for p in kwargs["participants"]
        ]

    if kwargs.get("recurrence"):
        rec = kwargs["recurrence"]
        rule = f"RRULE:FREQ={rec.freq.upper()}"
        if rec.interval:
            rule += f";INTERVAL={rec.interval}"
        if rec.by_day:
            rule += f";BYDAY={','.join(rec.by_day)}"
        if rec.by_month_day:
            rule += f";BYMONTHDAY={','.join(map(str, rec.by_month_day))}"
        if rec.until:
            rule += f";UNTIL={rec.until}"
        if rec.count:
            rule += f";COUNT={rec.count}"
        body["recurrence"] = [rule]

    if kwargs.get("reminders"):
        body["reminders"] = {
            "useDefault": False,
            "overrides": [
                {"method": r.method, "minutes": r.minutes}
                for r in kwargs["reminders"]
            ],
        }

    return body

@tool(args_schema=EventItem)
def process_event(config: RunnableConfig, **kwargs) -> dict:
    """
    Create, update, or delete a Google Calendar event for the given user.
    Supports timed and all-day events.
    Returns: { ok: bool, item_id: str|None, error: str|None, code: str|None }
    """
    start = pytime.time()
    user_id = config["configurable"].get("user_id", "unknown")
    if not user_id:
        return {"ok": False, "item_id": None, "error": "Missing user_id", "code": "no_user"}

    try:
        scheduling = config["configurable"]["scheduling"]
        result = scheduling.upsert_event(
            user_id,
            kwargs["command"],
            item_id=kwargs.get("item_id"),
            **{k: v for k, v in kwargs.items() if k not in ("command", "item_id")},
        )
        ok_val = 1 if result.get("ok") else 0
        track_tool_call(user_id=user_id, tool="process_event",
                        op=kwargs.get("command", "unknown"), item_type="event",
                        ok=ok_val, latency_ms=int((pytime.time() - start) * 1000),
                        error_code=result.get("code") if not ok_val else None)
        return result
    except Exception as e:
        track_tool_call(user_id=user_id, tool="process_event",
                        op=kwargs.get("command", "unknown"), item_type="event",
                        ok=0, latency_ms=int((pytime.time() - start) * 1000),
                        error_code="internal_error")
        return {"ok": False, "item_id": None, "error": str(e), "code": "exception"}

