from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from shared.user import get_user
from green_api.chats_history import get_last_messages_for_user

logger = logging.getLogger(__name__)


def _format_messages_for_llm(messages: List[Dict[str, Any]]) -> str:
    """Convert raw Green API messages into a single LLM-friendly transcript string."""
    summaries = []
    for m in messages:
        sender = "Outgoing" if m.get("type") == "outgoing" else "Incoming"
        msg_type = m.get("typeMessage", "unknown")
        chat = m.get("chatId", "")
        ts = m.get("timestamp")
        time_str = (
            datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "unknown time"
        )
        text = m.get("textMessage") or m.get("caption") or ""
        if msg_type in (
            "imageMessage", "videoMessage", "audioMessage",
            "stickerMessage", "documentMessage",
        ):
            media_url = m.get("downloadUrl") or "[no URL]"
            text = f"{text} [media: {media_url}]".strip()
        summaries.append(f"{sender} {msg_type} to {chat} at {time_str} — {text}".strip())
    return "\n".join(summaries)


class MessagingService:

    def resolve_recipients(self, user_id: str, name: str) -> List[Dict[str, Any]]:
        """
        Search the user's contact map for names matching *name*.
        Returns list of { "name": str, "chat_id": str|List[str] } sorted by match quality.
        """
        try:
            user = get_user(user_id)
            if not user:
                return []

            mapping: Dict[str, Any] = user.runtime.green_api_contacts or {}
            query = (name or "").strip().lower()
            results: List[tuple] = []

            for n, cid in mapping.items():
                if not n or not cid:
                    continue
                if query in n.lower():
                    results.append((n, cid))

            def _sort_key(item: tuple) -> tuple:
                n = item[0].lower()
                return (0 if n.startswith(query) else 1, len(n))

            results.sort(key=_sort_key)
            return [{"name": n, "chat_id": cid} for n, cid in results]
        except Exception:
            logger.exception("resolve_recipients failed for user %s", user_id)
            return []

    def search_history(self, user_id: str, chat_id: str, limit: int = 50) -> str:
        """
        Fetch the last *limit* messages for *chat_id* and return an LLM-ready transcript.
        """
        messages = get_last_messages_for_user(user_id, chat_id, limit)
        return _format_messages_for_llm(messages)
