from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from domain.inbound import InboundMessage, UserContext


class SchedulingService(Protocol):
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
    ) -> dict: ...

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
    ) -> dict: ...

    def upsert_event(
        self,
        user_id: str,
        command: str,
        *,
        item_id: Optional[str] = None,
        **kwargs: Any,
    ) -> dict: ...

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
    ) -> dict: ...

    def list_items(
        self,
        user_id: str,
        kind: str,
        status: str = "pending",
        from_date: Any = None,
        to_date: Any = None,
    ) -> List[dict]: ...


class MessagingService(Protocol):
    def resolve_recipients(self, user_id: str, name: str) -> List[Dict[str, Any]]: ...
    def search_history(self, user_id: str, chat_id: str, limit: int = 50) -> str: ...


class UserContextService(Protocol):
    def get(self, user_id: str) -> Optional[UserContext]: ...
    def remember_chat(self, user_id: str, chat_id: str, name: str) -> None: ...
    def save_token_usage(self, user_id: str, month: str, delta_tokens: int) -> None: ...


class Assistant(Protocol):
    async def handle(self, msg: InboundMessage, ctx: UserContext) -> str: ...
