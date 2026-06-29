"""
tests/test_infra_services.py

Unit tests for the three infra service classes.
All external I/O (Firestore, Green API, UserStore) is mocked — no network required.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_user(
    user_id="972500000001",
    name="Test User",
    timezone="Asia/Jerusalem",
    recent_chats=None,
    name2chat_id=None,
    green_api_contacts=None,
    monthly_token_usage=None,
):
    """Return a minimal mock User object."""
    runtime = MagicMock()
    runtime.recent_chats = recent_chats or {}
    runtime.name2chat_id = name2chat_id or {}
    runtime.green_api_contacts = green_api_contacts or {}
    runtime.monthlyTokenUsage = monthly_token_usage or {}
    runtime.greenApiInstance = MagicMock(id="inst1", token="tok1")

    config = MagicMock()
    config.name = name
    config.timezone = timezone

    user = MagicMock()
    user.user_id = user_id
    user.config = config
    user.runtime = runtime
    return user


# ─────────────────────────────────────────────────────────────────────────────
# SchedulingService
# ─────────────────────────────────────────────────────────────────────────────

class TestSchedulingService:

    def _service(self):
        from infra.services.scheduling_service import SchedulingService
        return SchedulingService()

    # ── upsert_reminder ───────────────────────────────────────────────────────

    def test_upsert_reminder_create_ok(self):
        svc = self._service()
        mock_store = MagicMock()
        mock_store.create_action_item.return_value = "item_abc"
        svc._action_store = lambda: mock_store

        result = svc.upsert_reminder(
            "u1", "create", title="Call dentist", dt="2025-09-01T10:00:00"
        )

        assert result["ok"] is True
        assert result["item_id"] == "item_abc"
        mock_store.create_action_item.assert_called_once_with(
            user_id="u1", item_type="reminder",
            title="Call dentist", description=None,
            dt="2025-09-01T10:00:00", location=None, op_id=None,
        )

    def test_upsert_reminder_create_missing_title(self):
        svc = self._service()
        result = svc.upsert_reminder("u1", "create")
        assert result["ok"] is False
        assert result["error"] == "missing_title"

    def test_upsert_reminder_update_ok(self):
        svc = self._service()
        mock_store = MagicMock()
        mock_store.update_action_item.return_value = True
        svc._action_store = lambda: mock_store

        result = svc.upsert_reminder(
            "u1", "update", item_id="item_abc", title="Call dentist (updated)"
        )

        assert result["ok"] is True
        assert result["item_id"] == "item_abc"

    def test_upsert_reminder_update_missing_item_id(self):
        svc = self._service()
        result = svc.upsert_reminder("u1", "update", title="x")
        assert result["ok"] is False
        assert result["error"] == "missing_item_id"

    def test_upsert_reminder_delete_ok(self):
        svc = self._service()
        mock_store = MagicMock()
        mock_store.delete_action_item.return_value = True
        svc._action_store = lambda: mock_store

        result = svc.upsert_reminder("u1", "delete", item_id="item_abc")

        assert result["ok"] is True
        assert result["item_id"] == "item_abc"

    def test_upsert_reminder_delete_not_found(self):
        svc = self._service()
        mock_store = MagicMock()
        mock_store.delete_action_item.return_value = False
        svc._action_store = lambda: mock_store

        result = svc.upsert_reminder("u1", "delete", item_id="ghost")

        assert result["ok"] is False
        assert result["code"] == "not_found"

    # ── upsert_task ───────────────────────────────────────────────────────────

    def test_upsert_task_create_uses_due_as_dt(self):
        svc = self._service()
        mock_store = MagicMock()
        mock_store.create_action_item.return_value = "task_1"
        svc._action_store = lambda: mock_store

        result = svc.upsert_task("u1", "create", title="Write report", due="2025-09-05")

        assert result["ok"] is True
        # dt should be the `due` value when `dt` is not provided
        call_kwargs = mock_store.create_action_item.call_args.kwargs
        assert call_kwargs["dt"] == "2025-09-05"
        assert call_kwargs["item_type"] == "task"

    # ── schedule_message ──────────────────────────────────────────────────────

    def test_schedule_message_create_ok(self):
        svc = self._service()
        mock_store = MagicMock()
        mock_store.save.return_value = "msg_99"
        svc._msg_store = lambda: mock_store

        result = svc.schedule_message(
            "u1", "create",
            message="Happy birthday!",
            scheduled_time="2025-09-10T09:00:00",
            recipient_name="Noa",
            recipient_chat_id="97250000@c.us",
        )

        assert result["ok"] is True
        assert result["item_id"] == "msg_99"
        mock_store.save.assert_called_once()

    def test_schedule_message_update_missing_item_id(self):
        svc = self._service()
        result = svc.schedule_message("u1", "update", message="new text")
        assert result["ok"] is False
        assert result["error"] == "missing_item_id"

    def test_schedule_message_delete_ok(self):
        svc = self._service()
        mock_store = MagicMock()
        mock_store.delete.return_value = True
        svc._msg_store = lambda: mock_store

        result = svc.schedule_message("u1", "delete", item_id="msg_99")

        assert result["ok"] is True

    def test_schedule_message_unknown_command(self):
        svc = self._service()
        result = svc.schedule_message("u1", "send", item_id="x")
        assert result["ok"] is False
        assert "unknown_command" in result["error"]

    # ── list_items ────────────────────────────────────────────────────────────

    def test_list_items_scheduled_messages(self):
        svc = self._service()
        mock_store = MagicMock()
        mock_store.get_items.return_value = [{"item_id": "m1"}]
        svc._msg_store = lambda: mock_store

        items = svc.list_items("u1", "scheduled_messages")

        assert items == [{"item_id": "m1"}]
        mock_store.get_items.assert_called_once_with("u1", "pending", None, None)

    def test_list_items_action_items(self):
        svc = self._service()
        mock_store = MagicMock()
        mock_store.get_items.return_value = [{"item_id": "a1"}, {"item_id": "a2"}]
        svc._action_store = lambda: mock_store

        items = svc.list_items("u1", "action_items", status="all")

        assert len(items) == 2

    def test_list_items_unknown_kind_returns_empty(self):
        svc = self._service()
        items = svc.list_items("u1", "bogus_kind")
        assert items == []


# ─────────────────────────────────────────────────────────────────────────────
# MessagingService
# ─────────────────────────────────────────────────────────────────────────────

class TestMessagingService:

    def _service(self):
        from infra.services.messaging_service import MessagingService
        return MessagingService()

    # ── resolve_recipients ────────────────────────────────────────────────────

    def test_resolve_recipients_prefix_match_first(self):
        svc = self._service()
        contacts = {
            "נועה כהן": "97250001@c.us",
            "נועם לוי": "97250002@c.us",
            "דני": "97250003@c.us",
        }
        user = _make_user(green_api_contacts=contacts)

        with patch("infra.services.messaging_service.get_user", return_value=user):
            results = svc.resolve_recipients("u1", "נועה")

        names = [r["name"] for r in results]
        assert "נועה כהן" in names
        assert names[0] == "נועה כהן"  # exact prefix first

    def test_resolve_recipients_no_match_returns_empty(self):
        svc = self._service()
        user = _make_user(green_api_contacts={"אבי": "97250001@c.us"})

        with patch("infra.services.messaging_service.get_user", return_value=user):
            results = svc.resolve_recipients("u1", "zzz_no_match")

        assert results == []

    def test_resolve_recipients_user_not_found(self):
        svc = self._service()
        with patch("infra.services.messaging_service.get_user", return_value=None):
            results = svc.resolve_recipients("u1", "anything")
        assert results == []

    def test_resolve_recipients_empty_query_returns_all(self):
        svc = self._service()
        contacts = {"א": "1@c.us", "ב": "2@c.us"}
        user = _make_user(green_api_contacts=contacts)

        with patch("infra.services.messaging_service.get_user", return_value=user):
            results = svc.resolve_recipients("u1", "")

        assert len(results) == 2

    # ── search_history ────────────────────────────────────────────────────────

    def test_search_history_returns_formatted_transcript(self):
        svc = self._service()
        raw_msgs = [
            {"type": "incoming", "typeMessage": "textMessage", "textMessage": "Hey",
             "chatId": "97250001@c.us", "timestamp": 1700000000},
            {"type": "outgoing", "typeMessage": "textMessage", "textMessage": "Hi back",
             "chatId": "97250001@c.us", "timestamp": 1700000060},
        ]

        with patch("infra.services.messaging_service.get_last_messages_for_user",
                   return_value=raw_msgs):
            transcript = svc.search_history("u1", "97250001@c.us", limit=10)

        assert "Incoming" in transcript
        assert "Hey" in transcript
        assert "Outgoing" in transcript
        assert "Hi back" in transcript

    def test_search_history_empty_returns_empty_string(self):
        svc = self._service()
        with patch("infra.services.messaging_service.get_last_messages_for_user",
                   return_value=[]):
            transcript = svc.search_history("u1", "97250001@c.us")
        assert transcript == ""


# ─────────────────────────────────────────────────────────────────────────────
# UserContextService
# ─────────────────────────────────────────────────────────────────────────────

class TestUserContextService:

    def _service(self):
        from infra.services.user_context_service import UserContextService
        return UserContextService()

    # ── get ───────────────────────────────────────────────────────────────────

    def test_get_returns_user_context(self):
        svc = self._service()
        user = _make_user(
            user_id="972500000001",
            name="Gaddy",
            timezone="Asia/Jerusalem",
            recent_chats={"נועה": "97250001@c.us"},
            name2chat_id={"נועה": ["97250001@c.us"]},
        )

        with patch("infra.services.user_context_service.get_user", return_value=user):
            ctx = svc.get("972500000001")

        from domain.inbound import UserContext
        assert isinstance(ctx, UserContext)
        assert ctx.user_id == "972500000001"
        assert ctx.name == "Gaddy"
        assert ctx.timezone == "Asia/Jerusalem"
        assert "נועה" in ctx.recent_chats

    def test_get_returns_none_for_unknown_user(self):
        svc = self._service()
        with patch("infra.services.user_context_service.get_user", return_value=None):
            ctx = svc.get("unknown")
        assert ctx is None

    # ── remember_chat ─────────────────────────────────────────────────────────

    def test_remember_chat_delegates_to_helper(self):
        svc = self._service()
        with patch(
            "infra.services.user_context_service.try_add_chat_to_recent_chats"
        ) as mock_fn:
            svc.remember_chat("u1", "97250001@c.us", "נועה")
        mock_fn.assert_called_once_with("u1", "97250001@c.us", "נועה")

    # ── save_token_usage ──────────────────────────────────────────────────────

    def test_save_token_usage_increments_and_saves(self):
        from infra.services.user_context_service import UserContextService
        from shared.user import TokenUsage

        svc = UserContextService()
        user = _make_user()
        user.runtime.monthlyTokenUsage = {}

        mock_store = MagicMock()

        with patch("infra.services.user_context_service.get_user", return_value=user), \
             patch("infra.services.user_context_service.UserContextService.save_token_usage") as _:
            pass  # just validate the patch path exists

        # Test the actual implementation directly
        with patch("shared.user.get_user", return_value=user), \
             patch("store.user.UserStore") as MockStore:
            instance = MockStore.return_value
            svc.save_token_usage("u1", "2025-09", 500)
            # Verify UserStore was created and save called
            MockStore.assert_called_once_with("u1")
            instance.save.assert_called_once_with(user)
            # Verify token was incremented
            usage = user.runtime.monthlyTokenUsage.get("2025-09")
            assert usage is not None
            assert usage.total == 500

    def test_save_token_usage_noop_for_unknown_user(self):
        svc = self._service()
        with patch("shared.user.get_user", return_value=None):
            # Should not raise
            svc.save_token_usage("ghost", "2025-09", 100)


# ─────────────────────────────────────────────────────────────────────────────
# domain/contracts.py — smoke tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDomainContracts:

    def test_action_item_summary_instantiation(self):
        from domain.contracts import ActionItemSummary
        s = ActionItemSummary(
            id="abc", action="Call dentist", action_type="reminder", time=None,
            participants=[], location=None
        )
        assert s.id == "abc"

    def test_scheduled_message_item_instantiation(self):
        from domain.contracts import ScheduledMessageItem
        m = ScheduledMessageItem(
            item_id="m1", command="create", item_type="message",
            message="Hey!", scheduled_time="2025-09-01T09:00:00",
            recipient_name="Noa", recipient_chat_id="97250001@c.us",
        )
        assert m.item_id == "m1"
        assert m.command == "create"


# ─────────────────────────────────────────────────────────────────────────────
# domain/inbound.py — smoke tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDomainInbound:

    def test_inbound_message(self):
        from domain.inbound import InboundMessage
        msg = InboundMessage(user_id="u1", sender_name="Gaddy", text="stt: hello")
        assert msg.text == "stt: hello"

    def test_user_context(self):
        from domain.inbound import UserContext
        ctx = UserContext(user_id="u1", name="Gaddy", timezone="UTC")
        assert ctx.recent_chats == {}
        assert ctx.name2chat_id == {}


# ─────────────────────────────────────────────────────────────────────────────
# assistant/schemas.py — smoke tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAssistantSchemas:

    def test_reminder_item(self):
        from assistant.schemas import ReminderItem
        r = ReminderItem(command="create", title="Test", datetime="2025-09-01T09:00:00")
        assert r.item_type == "reminder"

    def test_task_item(self):
        from assistant.schemas import TaskItem
        t = TaskItem(command="create", title="Finish report")
        assert t.item_type == "task"
        assert t.completed is False

    def test_event_item_defaults(self):
        from assistant.schemas import EventItem
        e = EventItem(command="create", title="Meeting")
        assert e.item_type == "event"
        assert e.all_day is False
        assert e.participants is None
