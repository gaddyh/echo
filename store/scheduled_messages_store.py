from __future__ import annotations

import logging
from typing import Optional, List, Union
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from domain.contracts import ScheduledMessageItem
from db.base import db  # Firestore client
from google.cloud.firestore_v1.base_document import DocumentSnapshot
from shared.user import get_user
from store.user import UserStore
from shared import time  # provides parse_datetime(str)->datetime
# If you keep per-user tz, prefer fetching it; fallback stays Asia/Jerusalem.

logger = logging.getLogger(__name__)
DEFAULT_TZ = ZoneInfo("Asia/Jerusalem")


def _ensure_aware_utc(dt: datetime) -> datetime:
    """Normalize any datetime to aware UTC (naive => assume UTC)."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_to_utc(dt_in: Optional[Union[str, datetime]]) -> Optional[datetime]:
    """
    Parse ISO-8601 string or datetime. If naive, localize to DEFAULT_TZ, then convert to UTC.
    Returns None if input is falsy.
    """
    if not dt_in:
        return None
    parsed = dt_in if isinstance(dt_in, datetime) else time.parse_datetime(dt_in)
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        parsed = parsed.replace(tzinfo=DEFAULT_TZ)
    return parsed.astimezone(timezone.utc)


class ScheduledMessageStore:
    def __init__(self):
        self.db = db
        self.collection = self.db.collection("scheduled_messages")

    def save(self, user_id: str, item: ScheduledMessageItem) -> str:
        """
        Create a new scheduled message with auto-generated ID.
        Idempotency: if item.op_id exists, return existing doc with same (user_id, op_id).
        """
        # Optional idempotency
        op_id = getattr(item, "op_id", None)
        if op_id:
            q = (
                self.collection.where("user_id", "==", user_id)
                .where("op_id", "==", op_id)
                .limit(1)
            )
            existing = list(q.stream())
            if existing:
                logger.info("[STORE] Idempotent hit for op_id=%s user=%s", op_id, user_id)
                return existing[0].id

        doc_ref = self.collection.document()  # auto-generated ID
        item_id = doc_ref.id
        logger.info("[STORE] Saving scheduled message %s for user %s", item_id, user_id)

        dt_utc = _parse_to_utc(item.scheduled_time)
        now_iso = datetime.now(timezone.utc).isoformat()

        doc = {
            "user_id": user_id,
            "item_id": item_id,
            "command": item.command,
            "item_type": item.item_type,
            "message": item.message,
            "scheduled_time": dt_utc,  # Firestore Timestamp
            "recipient_name": item.recipient_name,
            "recipient_chat_id": item.recipient_chat_id,
            "status": "pending",
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        if op_id:
            doc["op_id"] = op_id

        doc_ref.set(doc)

        # Persist name→chat mapping if runtime exists
        try:
            user = get_user(user_id)
            runtime = getattr(user, "runtime", None)
            if runtime is not None:
                name2chat = getattr(runtime, "name2chat_id", {}) or {}
                name2chat[item.recipient_name] = item.recipient_chat_id
                user.runtime.name2chat_id = [name2chat]
                UserStore(user_id).save(user)
        except Exception:
            logger.exception("[STORE] Failed to persist name2chat_id for user %s", user_id)

        return item_id

    def update(self, item_id: str, updates: dict) -> bool:
        """Update only non-None fields of an existing scheduled message."""
        logger.info("[STORE] Updating scheduled message %s", item_id)
        doc_ref = self.collection.document(item_id)
        snap = doc_ref.get()
        if not snap.exists:
            return False

        clean_updates = {k: v for k, v in updates.items() if v is not None}

        if "scheduled_time" in clean_updates:
            clean_updates["scheduled_time"] = _parse_to_utc(clean_updates["scheduled_time"])

        clean_updates["updated_at"] = datetime.now(timezone.utc).isoformat()

        if clean_updates:
            doc_ref.update(clean_updates)
        return True

    def get(self, item_id: str) -> Optional[dict]:
        """Retrieve a scheduled message item by ID."""
        doc = self.collection.document(item_id).get()
        if doc.exists:
            return {"item_id": item_id, **doc.to_dict()}
        return None

    def delete(self, item_id: str) -> bool:
        """Delete a scheduled message item by ID."""
        logger.info("[STORE] Deleting scheduled message %s", item_id)
        doc_ref = self.collection.document(item_id)
        if doc_ref.get().exists:
            doc_ref.delete()
            return True
        return False

    def list_by_user(self, user_id: str) -> List[dict]:
        """List all scheduled messages for a specific user."""
        logger.info("[STORE] Listing scheduled messages for user %s", user_id)
        docs = self.collection.where("user_id", "==", user_id).stream()
        return [
            {"item_id": doc.id, **doc.to_dict()}
            for doc in docs
            if isinstance(doc, DocumentSnapshot) and doc.exists
        ]

    def query_scheduled_messages(self, start: datetime, end: Optional[datetime] = None) -> List[dict]:
        """
        Query scheduled messages across all users between start and end (for dispatching).
        Expects UTC; normalizes just in case.
        """
        start_utc = _ensure_aware_utc(start)
        end_utc = _ensure_aware_utc(end) if end else start_utc + timedelta(minutes=1)

        query = (
            self.collection
            .where("status", "in", ["pending", "failed"])
            .where("scheduled_time", ">=", start_utc)
            .where("scheduled_time", "<=", end_utc)
        )
        results = query.stream()
        return [{"item_id": doc.id, **doc.to_dict()} for doc in results if doc.exists]

    def get_upcoming(self, user_id: str) -> List[dict]:
        """Fetch upcoming scheduled messages for a user (next 7 days), status 'pending'."""
        now = _ensure_aware_utc(datetime.utcnow())
        future = now + timedelta(days=7)

        query = (
            self.collection
            .where("user_id", "==", user_id)
            .where("status", "==", "pending")
            .where("scheduled_time", ">=", now)
            .where("scheduled_time", "<=", future)
        )
        results = query.stream()
        return [{"item_id": doc.id, **doc.to_dict()} for doc in results if doc.exists]

    def get_items(
        self,
        user_id: str,
        status: Literal["all", "pending", "completed"] = "pending",
        from_date: datetime = None,
        to_date: datetime = None,
    ) -> List[dict]:
        """
        Fetch items by either status or date range.
        Note: "completed" maps to "sent" for scheduled messages.
        """
        query = self.collection.where("user_id", "==", user_id)

        if status != "all":
            status_value = "sent" if status == "completed" else status
            query = query.where("status", "==", status_value)

        if from_date is not None:
            query = query.where("scheduled_time", ">=", _ensure_aware_utc(from_date))
        if to_date is not None:
            query = query.where("scheduled_time", "<=", _ensure_aware_utc(to_date))

        try:
            query = query.order_by("scheduled_time")
        except Exception:
            pass

        results = query.stream()
        return [{"item_id": doc.id, **doc.to_dict()} for doc in results if doc.exists]

    def update_status(self, item_id: str, status: str) -> bool:
        doc_ref = self.collection.document(item_id)
        snap = doc_ref.get()
        if not snap.exists:
            return False
        doc_ref.update({
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        return True

    def create_scheduled_message(
        self,
        user_id: str,
        recipient_chat_id: str,
        message: str,
        dt: datetime,
        recipient_name: str | None = None,
        op_id: str | None = None,
    ) -> str:
        """Convenience helper for tests/dev."""
        doc_ref = self.collection.document()
        item_id = doc_ref.id
        now_iso = datetime.now(timezone.utc).isoformat()

        doc = {
            "user_id": user_id,
            "item_id": item_id,
            "message": message,
            "recipient_chat_id": recipient_chat_id,
            "recipient_name": recipient_name or recipient_chat_id,
            "scheduled_time": dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc),
            "status": "pending",
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        if op_id:
            doc["op_id"] = op_id

        doc_ref.set(doc)
        return item_id
