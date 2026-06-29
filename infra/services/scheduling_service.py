from __future__ import annotations

import logging
from typing import Any, List, Optional

from domain.contracts import ScheduledMessageItem
from store.action_item_store import ActionItemStore
from store.scheduled_messages_store import ScheduledMessageStore

logger = logging.getLogger(__name__)


# ── Result helpers ─────────────────────────────────────────────────────────────

def _ok(item_id: Optional[str] = None) -> dict:
    return {"ok": True, "item_id": item_id, "error": None, "code": None}


def _fail(msg: str, code: Optional[str] = None) -> dict:
    return {"ok": False, "item_id": None, "error": msg, "code": code or "bad_request"}


# ── Google Calendar event body builder (moved from assistant/tools/process_event.py) ──

def build_event_body(kwargs: dict) -> dict:
    """Build a Google Calendar API event body from EventItem keyword-args."""
    body: dict = {
        "summary": kwargs["title"],
        "description": kwargs.get("description"),
    }

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


# ── SchedulingService ──────────────────────────────────────────────────────────

class SchedulingService:

    # ── Internal store factories (one instance per call keeps tests simple) ────

    def _action_store(self) -> ActionItemStore:
        return ActionItemStore()

    def _msg_store(self) -> ScheduledMessageStore:
        return ScheduledMessageStore()

    # ── Reminders ─────────────────────────────────────────────────────────────

    def upsert_reminder(
        self,
        user_id: str,
        command: str,
        *,
        item_id: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        dt: Optional[str] = None,
        status: Optional[str] = None,
        op_id: Optional[str] = None,
    ) -> dict:
        return self._upsert_action_item(
            user_id, command, "reminder",
            item_id=item_id, title=title, description=description,
            dt=dt, status=status, op_id=op_id,
        )

    # ── Tasks ──────────────────────────────────────────────────────────────────

    def upsert_task(
        self,
        user_id: str,
        command: str,
        *,
        item_id: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        dt: Optional[str] = None,
        due: Optional[str] = None,
        completed: Optional[bool] = None,
        list_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        position: Optional[str] = None,
        status: Optional[str] = None,
        op_id: Optional[str] = None,
    ) -> dict:
        return self._upsert_action_item(
            user_id, command, "task",
            item_id=item_id, title=title, description=description,
            dt=dt or due, status=status, op_id=op_id,
        )

    # ── Action items (reminder + task share Firestore store) ──────────────────

    def _upsert_action_item(
        self,
        user_id: str,
        command: str,
        item_type: str,
        *,
        item_id: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        dt: Optional[str] = None,
        location: Optional[str] = None,
        status: Optional[str] = None,
        op_id: Optional[str] = None,
    ) -> dict:
        store = self._action_store()
        try:
            if command == "create":
                if not title:
                    return _fail("missing_title")
                new_id = store.create_action_item(
                    user_id=user_id,
                    item_type=item_type,
                    title=title,
                    description=description,
                    dt=dt,
                    location=location,
                    op_id=op_id,
                )
                return _ok(new_id)

            if command == "update":
                if not item_id:
                    return _fail("missing_item_id")
                updated = store.update_action_item(
                    user_id=user_id,
                    item_id=item_id,
                    item_type=item_type,
                    title=title,
                    description=description,
                    dt=dt,
                    location=location,
                    status=status,
                )
                return _ok(item_id) if updated else _fail("not_found", "not_found")

            if command == "delete":
                if not item_id:
                    return _fail("missing_item_id")
                deleted = store.delete_action_item(user_id=user_id, item_id=item_id)
                return _ok(item_id) if deleted else _fail("not_found", "not_found")

            return _fail(f"unknown_command: {command}")
        except Exception:
            logger.exception("_upsert_action_item failed for user %s", user_id)
            return _fail("internal_error", "internal_error")

    # ── Calendar events ────────────────────────────────────────────────────────

    def upsert_event(
        self,
        user_id: str,
        command: str,
        *,
        item_id: Optional[str] = None,
        **kwargs: Any,
    ) -> dict:
        try:
            from shared.google_calendar.tokens import get_valid_credentials
            from googleapiclient.discovery import build

            creds = get_valid_credentials(user_id)
            if not creds:
                return _fail("No valid credentials", "no_creds")

            service = build("calendar", "v3", credentials=creds)

            if command in ("update", "delete") and not item_id:
                return _fail("missing_item_id")

            if command == "create":
                body = build_event_body(kwargs)
                event = service.events().insert(calendarId="primary", body=body).execute()
                return _ok(event["id"])

            if command == "update":
                body = build_event_body(kwargs)
                event = service.events().patch(
                    calendarId="primary", eventId=item_id, body=body
                ).execute()
                return _ok(event["id"])

            if command == "delete":
                service.events().delete(calendarId="primary", eventId=item_id).execute()
                return _ok(item_id)

            return _fail(f"unknown_command: {command}")

        except ValueError as ve:
            return _fail(str(ve), "bad_input")
        except Exception as e:
            logger.exception("upsert_event failed for user %s", user_id)
            return _fail(str(e), "exception")

    # ── Scheduled messages ─────────────────────────────────────────────────────

    def schedule_message(
        self,
        user_id: str,
        command: str,
        *,
        item_id: Optional[str] = None,
        message: Optional[str] = None,
        scheduled_time: Optional[str] = None,
        recipient_name: Optional[str] = None,
        recipient_chat_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict:
        store = self._msg_store()
        try:
            if command == "create":
                item = ScheduledMessageItem(
                    item_id=item_id or "",
                    command=command,
                    message=message or "",
                    scheduled_time=scheduled_time or "",
                    recipient_name=recipient_name or "",
                    recipient_chat_id=recipient_chat_id or "",
                    status=status,
                )
                new_id = store.save(user_id=user_id, item=item)
                return _ok(new_id)

            if command == "update":
                if not item_id:
                    return _fail("missing_item_id")
                updates = {
                    "message": message,
                    "scheduled_time": scheduled_time,
                    "status": status,
                }
                ok = store.update(item_id=item_id, updates=updates)
                return _ok(item_id) if ok else _fail("not_found", "not_found")

            if command == "delete":
                if not item_id:
                    return _fail("missing_item_id")
                deleted = store.delete(item_id=item_id)
                return _ok(item_id) if deleted else _fail("not_found", "not_found")

            return _fail(f"unknown_command: {command}")
        except Exception:
            logger.exception("schedule_message failed for user %s", user_id)
            return _fail("internal_error", "internal_error")

    # ── List ───────────────────────────────────────────────────────────────────

    def list_items(
        self,
        user_id: str,
        kind: str,
        status: str = "pending",
        from_date: Any = None,
        to_date: Any = None,
    ) -> List[dict]:
        try:
            if kind == "scheduled_messages":
                return self._msg_store().get_items(user_id, status, from_date, to_date)
            if kind == "action_items":
                return self._action_store().get_items(user_id, status, from_date, to_date)
            logger.warning("list_items: unknown kind %r", kind)
            return []
        except Exception:
            logger.exception("list_items failed for user %s", user_id)
            return []
