"""
tests/test_int_scheduler.py

End-to-end verification of the scheduling pipeline:
  SchedulingService.upsert_reminder → Firestore → trigger_events() → fires

The adapter's send_message_360dialog is monkeypatched so no real
WhatsApp messages are sent during the test.
"""
import pytest
from unittest.mock import AsyncMock, patch
from shared.time import utcnow
from infra.services.scheduling_service import SchedulingService
import shared.event_trigger as trigger_module

pytestmark = pytest.mark.integration


@pytest.fixture
def svc():
    return SchedulingService()


async def test_reminder_created_and_triggered(real_user_id, svc, monkeypatch):
    """
    Creates a reminder due right now via SchedulingService,
    runs trigger_events(), and asserts it was picked up and sent.
    """
    sent: list[tuple] = []

    async def mock_send(user_id: str, message: str) -> bool:
        sent.append((user_id, message))
        return True

    # Patch the adapter used by event_trigger
    monkeypatch.setattr(trigger_module.adapter, "send_message_360dialog", mock_send)

    # Create a reminder due right now
    result = svc.upsert_reminder(
        real_user_id,
        "create",
        title="Integration test reminder — safe to delete",
        dt=utcnow().isoformat(),
    )
    assert result["ok"] is True, f"upsert_reminder failed: {result}"
    item_id = result["item_id"]

    try:
        await trigger_module.trigger_events()

        # The reminder should have been sent to the test user
        assert any(uid == real_user_id for uid, _ in sent), (
            f"trigger_events() ran but no message was sent for user {real_user_id}. "
            f"Sent calls: {sent}"
        )
    finally:
        # Cleanup — delete the test reminder regardless of outcome
        svc.upsert_reminder(real_user_id, "delete", item_id=item_id)


async def test_scheduled_message_created_and_triggered(real_user_id, svc, monkeypatch):
    """
    Creates a scheduled message due right now via SchedulingService,
    runs trigger_events(), and asserts send_message_from_me was called.
    """
    sent: list[tuple] = []

    def mock_send_from_me(user_id: str, chat_id: str, message: str) -> str:
        sent.append((user_id, chat_id, message))
        return "fake-msg-id"

    monkeypatch.setattr(trigger_module, "send_message_from_me", mock_send_from_me)

    result = svc.schedule_message(
        real_user_id,
        "create",
        message="Integration test scheduled message — safe to ignore",
        scheduled_time=utcnow().isoformat(),
        recipient_name="Test",
        recipient_chat_id=f"{real_user_id}@c.us",
    )
    assert result["ok"] is True, f"schedule_message failed: {result}"
    item_id = result["item_id"]

    try:
        await trigger_module.trigger_events()

        assert any(uid == real_user_id for uid, _, _ in sent), (
            f"trigger_events() ran but send_message_from_me was not called for {real_user_id}. "
            f"Sent calls: {sent}"
        )
    finally:
        svc.schedule_message(real_user_id, "delete", item_id=item_id)


async def test_list_items_matches_firestore(real_user_id, svc):
    """
    Creates an action item, lists pending items, confirms it appears, then deletes it.
    """
    result = svc.upsert_task(
        real_user_id,
        "create",
        title="Integration list test task",
    )
    assert result["ok"] is True
    item_id = result["item_id"]

    try:
        items = svc.list_items(real_user_id, "action_items", status="all")
        ids = [i.get("id") or i.get("item_id") for i in items]
        assert item_id in ids, (
            f"Created task {item_id} not found in list_items result: {ids}"
        )
    finally:
        svc.upsert_task(real_user_id, "delete", item_id=item_id)
