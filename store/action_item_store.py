from __future__ import annotations

import logging
from typing import List, Optional, Union
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from context.agents.action_item import ActionItemSummary
from db.base import db  # Firestore client
from shared import time  # provides parse_datetime(dt_str) and utcnow()/utcnow?; we'll guard TZ

logger = logging.getLogger(__name__)
DEFAULT_TZ = ZoneInfo("Asia/Jerusalem")


def _ensure_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_to_utc(dt_in: Optional[Union[str, datetime]]) -> Optional[datetime]:
    """
    Parse ISO-8601 string (or datetime). If naive, localize to DEFAULT_TZ, then convert to UTC.
    Returns None if input is falsy.
    """
    if not dt_in:
        return None
    if isinstance(dt_in, datetime):
        parsed = dt_in
    else:
        parsed = time.parse_datetime(dt_in)  # may be naive or aware
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        parsed = parsed.replace(tzinfo=DEFAULT_TZ)
    return parsed.astimezone(timezone.utc)


class ActionItemStore:
    def __init__(self):
        self.db = db
        self.collection = db.collection("my_actions")

    def update_status(self, user_id: str, item_id: str, status: str) -> bool:
        try:
            doc_ref = self.collection.document(item_id)
            snap = doc_ref.get()
            if not snap.exists:
                logger.info("[STORE] update_status: item %s not found", item_id)
                return False
            data = snap.to_dict() or {}
            if data.get("user_id") != user_id:
                logger.warning("[STORE] update_status: user mismatch for item %s", item_id)
                return False
            updates = {
                "status": status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            doc_ref.update(updates)
            logger.info("[STORE] Updated status of action item %s for user %s", item_id, user_id)
            return True
        except Exception:
            logger.exception("[STORE] update_status failed for %s", item_id)
            return False

    def create_action_item(
        self,
        user_id: str,
        item_type: str,
        title: str,
        description: Optional[str],
        dt: Optional[Union[str, datetime]],
        location: Optional[str],
        op_id: Optional[str] = None,
    ) -> str:
        """
        Create a new action item. Returns the Firestore-generated item_id.
        Idempotent on (user_id, op_id) if op_id is provided.
        """
        try:
            # Idempotency: return existing item if same (user_id, op_id)
            if op_id:
                q = (
                    self.collection.where("user_id", "==", user_id)
                    .where("op_id", "==", op_id)
                    .limit(1)
                )
                existing = list(q.stream())
                if existing:
                    return existing[0].id

            dt_utc = _parse_to_utc(dt)

            doc_ref = self.collection.document()
            now_iso = datetime.now(timezone.utc).isoformat()
            doc = {
                "user_id": user_id,
                "item_id": doc_ref.id,
                "item_type": item_type,
                "title": title,
                "description": description,
                "datetime": dt_utc,  # Firestore Timestamp
                "location": location,
                "created_at": now_iso,
                "updated_at": now_iso,
                "status": "pending",
            }
            if op_id:
                doc["op_id"] = op_id

            doc_ref.set(doc)
            logger.info("[STORE] Created action item %s for user %s", doc_ref.id, user_id)
            return doc_ref.id
        except Exception:
            logger.exception("[STORE] create_action_item failed for user %s", user_id)
            raise

    def update_action_item(
        self,
        user_id: str,
        item_id: str,
        item_type: str,
        title: Optional[str],
        description: Optional[str],
        dt: Optional[Union[str, datetime]],
        location: Optional[str],
        status: Optional[str],
    ) -> bool:
        """
        Update an existing action item. Returns success status.
        * Does not allow changing item_type (ignored if provided).
        * Converts datetime to aware UTC.
        * Verifies ownership (user_id).
        """
        try:
            doc_ref = self.collection.document(item_id)
            snap = doc_ref.get()
            if not snap.exists:
                logger.info("[STORE] update_action_item: item %s not found", item_id)
                return False

            current = snap.to_dict() or {}
            if current.get("user_id") != user_id:
                logger.warning("[STORE] update_action_item: user mismatch for item %s", item_id)
                return False

            updates: dict = {}

            if item_type and item_type != current.get("item_type"):
                logger.info(
                    "[STORE] update_action_item: ignoring item_type change (%s -> %s) for %s",
                    current.get("item_type"), item_type, item_id
                )

            if title:
                updates["title"] = title
            if description:
                updates["description"] = description
            if dt:
                updates["datetime"] = _parse_to_utc(dt)
            if location:
                updates["location"] = location
            if status:
                updates["status"] = status

            updates["updated_at"] = datetime.now(timezone.utc).isoformat()

            if not updates:
                logger.info("[STORE] update_action_item: no-op for %s", item_id)
                return True

            doc_ref.update(updates)
            logger.info("[STORE] Updated action item %s for user %s", item_id, user_id)
            return True
        except Exception:
            logger.exception("[STORE] update_action_item failed for %s", item_id)
            return False

    def delete_action_item(self, user_id: str, item_id: str) -> bool:
        try:
            doc_ref = self.collection.document(item_id)
            snap = doc_ref.get()
            if not snap.exists:
                logger.info("[STORE] delete_action_item: item %s not found", item_id)
                return False
            data = snap.to_dict() or {}
            if data.get("user_id") != user_id:
                logger.warning("[STORE] delete_action_item: user mismatch for item %s", item_id)
                return False

            doc_ref.delete()
            logger.info("[STORE] Deleted action item %s for user %s", item_id, user_id)
            return True
        except Exception:
            logger.exception("[STORE] delete_action_item failed for %s", item_id)
            return False

    def query_action_items(self, start: datetime, end: Optional[datetime] = None) -> List[dict]:
        """
        Query action items across all users between start and end (for notifications).
        Expects datetimes around UTC; normalizes to aware UTC just in case.
        """
        try:
            start_utc = _ensure_aware_utc(start)
            end_utc = _ensure_aware_utc(end) if end else start_utc + timedelta(minutes=1)

            query = (
                self.collection.where("status", "in", ["pending", "failed"])
                .where("datetime", ">=", start_utc)
                .where("datetime", "<=", end_utc)
            )
            results = query.stream()
            items = []
            for doc in results:
                data = doc.to_dict()
                items.append(data)
            return items
        except Exception:
            logger.exception("[STORE] query_action_items failed")
            return []

    async def get_upcoming(self, user_id: str) -> List[ActionItemSummary]:
        """
        Fetch upcoming ActionItems for a user (next 7 days), status 'pending'.
        """
        try:
            now = getattr(time, "utcnow", None)() if hasattr(time, "utcnow") else datetime.utcnow()
            now = _ensure_aware_utc(now)
            future = now + timedelta(days=7)

            query = (
                self.collection.where("user_id", "==", user_id)
                .where("status", "==", "pending")
                .where("datetime", ">=", now)
                .where("datetime", "<=", future)
            )

            results = query.stream()
            summaries: List[ActionItemSummary] = []
            for doc in results:
                data = doc.to_dict()
                summaries.append(
                    ActionItemSummary(
                        id=doc.id,
                        action=data["title"],
                        action_type=data["item_type"],
                        time=data.get("datetime"),
                        participants=[],
                        location=data.get("location"),
                    )
                )
            return summaries
        except Exception:
            logger.exception("[STORE] get_upcoming failed for user %s", user_id)
            return []

    def get_items(
        self,
        user_id: str,
        status: Literal["all", "pending", "completed"] = "pending",
        from_date: datetime = None,
        to_date: datetime = None,
    ) -> List[dict]:
        """
        Fetch items by either status or date range.
        Returns a list of dicts with {"item_id": <id>, ...doc fields...}
        """
        try:
            query = self.collection.where("user_id", "==", user_id)

            if status != "all":
                query = query.where("status", "==", status)

            if from_date is not None:
                query = query.where("datetime", ">=", _ensure_aware_utc(from_date))
            if to_date is not None:
                query = query.where("datetime", "<=", _ensure_aware_utc(to_date))

            try:
                query = query.order_by("datetime")
            except Exception:
                pass

            results = query.stream()
            return [{"item_id": doc.id, **doc.to_dict()} for doc in results if doc.exists]
        except Exception:
            logger.exception("[STORE] get_items failed for user %s", user_id)
            return []
