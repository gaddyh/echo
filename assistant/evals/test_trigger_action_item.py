import os
import pytest
from shared import time

pytestmark = pytest.mark.skipif(
    not os.path.exists(".secrets/firebase1.json"),
    reason="integration test — requires real Firebase credentials (.secrets/firebase1.json)"
)

from store.action_item_store import ActionItemStore
from store.scheduled_messages_store import ScheduledMessageStore
from store.delivery_mng_store import SendingStatusStore
import shared.event_trigger as trigger_events


# --- Helpers ---
class DummyAdapter:
    """Fake 360dialog adapter for ActionItems"""
    def __init__(self):
        self.success = False
    async def send_message_360dialog(self, user_id, message):
        return self.success


class DummySender:
    """Fake sender for send_message_from_me"""
    def __init__(self):
        self.calls = []  # record calls
        self.success = False
    def send(self, user_id, recipient_chat_id, message):
        self.calls.append((user_id, recipient_chat_id, message))
        return self.success


@pytest.mark.asyncio
async def test_action_item_retry(monkeypatch):
    """ActionItem should increment retries on failure, reset on success (no Echo fallback)."""
    user_id = "972546610653"
    store = ActionItemStore()
    item_id = store.create_action_item(
        user_id=user_id,
        item_type="reminder",
        title="hello world",
        description=None,
        dt=time.utcnow(),   # due now
        location=None,
    )

    status_store = SendingStatusStore(user_id)
    status_store.create_or_get(item_id, "action_item")

    # Patch adapter to fail first, succeed second
    dummy = DummyAdapter()
    monkeypatch.setattr(trigger_events, "adapter", dummy)

    # Run once (fail)
    await trigger_events.trigger_events()
    status = status_store.get(item_id, "action_item")
    assert status["retry_count"] == 1
    assert status["last_status"] == "failed"

    # Run again (success)
    dummy.success = True
    await trigger_events.trigger_events()
    status = status_store.get(item_id, "action_item")
    assert status["retry_count"] == 0
    assert status["last_status"] == "completed"


@pytest.mark.asyncio
async def test_scheduled_message_retry_and_echo(monkeypatch):
    """ScheduledMessage should escalate to Echo after MAX_RETRIES."""
    user_id = "972546610653"
    sched_store = ScheduledMessageStore()
    item_id = sched_store.create_scheduled_message(
        user_id=user_id,
        recipient_chat_id="98765@c.us",
        recipient_name="test",
        message="send this please",
        dt=time.utcnow(),   # due now
    )

    status_store = SendingStatusStore(user_id)
    status_store.create_or_get(item_id, "scheduled_message")

    # Patch sender to always fail
    dummy_sender = DummySender()
    monkeypatch.setattr(trigger_events, "send_message_from_me", dummy_sender.send)

    # Run enough times to exceed MAX_RETRIES
    for _ in range(trigger_events.MAX_RETRIES):
        await trigger_events.trigger_events()

    status = status_store.get(item_id, "scheduled_message")
    # After MAX_RETRIES, it should escalate to Echo
    assert status["last_status"] == "failed_echo"
    assert "max retries exceeded" in status["last_error"]

    # Check Echo fallback was called
    assert any(
        call[1] == trigger_events.ECHO_CHAT_ID and "Please send this message yourself" in call[2]
        for call in dummy_sender.calls
    )
