# Firestore-only MVP tools:
# - get_items
# - search_chat_history
# - get_candidate_recipient_chat_ids
# - process_contact_message
# Plus helpers for recent chats management and datetime normalization.

from __future__ import annotations

import logging
import time as pytime
from typing import Literal, Optional, List, Dict, Tuple
from datetime import datetime, timezone

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from zoneinfo import ZoneInfo

from adapters.whatsapp.wwebjs.wwebjs_adapter import get_chat_history
from store.action_item_store import ActionItemStore
from store.scheduled_messages_store import ScheduledMessageStore

from shared.user import get_user, RECENT_CHATS_LIMIT
from store.user import UserStore

from langchain_tavily import TavilySearch
from context.agents.action_item import ScheduledMessageItem
from agents.echo.tools.helper import build_llm_history, try_add_chat_to_recent_chats

# NEW: analytics
from shared.observability.metrics import track_tool_call

# ----------------------
# External search tool
# ----------------------
tavily_search_tool = TavilySearch(
    max_results=5,
    topic="general",
)

# ----------------------
# Helpers
# ----------------------
DEFAULT_TZ = ZoneInfo("Asia/Jerusalem")
MAX_LIMIT = 200

def _user_tz(user_id: str) -> ZoneInfo:
    try:
        user = get_user(user_id)
        tz_name = getattr(getattr(user, "profile", None), "tz", None)
        return ZoneInfo(tz_name) if tz_name else DEFAULT_TZ
    except Exception:
        return DEFAULT_TZ


def _to_utc(dt: Optional[datetime], user_tz: ZoneInfo) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=user_tz).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


def _ok(payload: dict) -> dict:
    return {"ok": True, **payload}


def _fail(msg: str, payload: Optional[dict] = None) -> dict:
    base = {"ok": False, "error": msg}
    if payload:
        base.update(payload)
    return base

def _parse_iso8601(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s2)
    except Exception:
        return None


# ----------------------
# get_items
# ----------------------
@tool
def get_items(
    config: RunnableConfig,
    type: Literal["scheduled_messages", "action_items"],
    status: Literal["all", "pending", "completed"] = "pending",
    from_date: datetime = None,
    to_date: datetime = None,
) -> dict:
    """
    Get scheduled messages or action items by status and/or date range.
    Returns: { ok: bool, items: list, error?: str }
    """
    user_id = config["configurable"]["user_id"]
    user_tz = _user_tz(user_id)
    start = pytime.time()

    try:
        from_date_utc = _to_utc(from_date, user_tz) if from_date else None
    except Exception:
        logging.exception("get_items: failed to convert from_date")
        from_date_utc = None

    try:
        to_date_utc = _to_utc(to_date, user_tz) if to_date else None
    except Exception:
        logging.exception("get_items: failed to convert to_date")
        to_date_utc = None

    try:
        if type == "scheduled_messages":
            store = ScheduledMessageStore()
            items = store.get_items(user_id, status, from_date_utc, to_date_utc)
            track_tool_call(
                user_id=user_id, tool="get_items", op="query", item_type=type,
                ok=1, latency_ms=int((pytime.time() - start) * 1000)
            )
            return _ok({"items": items})
        elif type == "action_items":
            store = ActionItemStore()
            items = store.get_items(user_id, status, from_date_utc, to_date_utc)
            track_tool_call(
                user_id=user_id, tool="get_items", op="query", item_type=type,
                ok=1, latency_ms=int((pytime.time() - start) * 1000)
            )
            return _ok({"items": items})
        else:
            track_tool_call(
                user_id=user_id, tool="get_items", op="query", item_type=type,
                ok=0, latency_ms=int((pytime.time() - start) * 1000), error_code="unknown_type"
            )
            return _fail("unknown_type", {"items": []})
    except Exception:
        logging.exception("get_items: failed to get items")
        track_tool_call(
            user_id=user_id, tool="get_items", op="query", item_type=type,
            ok=0, latency_ms=int((pytime.time() - start) * 1000), error_code="internal_error"
        )
        return _fail("internal_error", {"items": []})

# ----------------------
# search_chat_history
# ----------------------
from typing import Any, Dict, List

# ── Minimal, LLM-ready history: [{id, text[, ref_id]}] ─────────────────────────

MEDIA_LABEL = {
    "imagemessage": "🖼️ Image",
    "videomessage": "🎞️ Video",
    "audiomessage": "🎤 Voice note",
    "ptt":           "🎤 Voice note",
    "stickermessage":"🏷️ Sticker",
    "documentmessage":"📄 Document",
    "locationmessage":"📍 Location",
}

def _norm(s: Any) -> str:
    return s if isinstance(s, str) else ""

def _kind(m: Dict[str, Any]) -> str:
    tm = _norm(m.get("typeMessage")).lower()
    if not tm:
        tm = _norm(m.get("type")).lower()  # some SDKs misuse 'type'
    return tm or "textmessage"

def _message_text(m: Dict[str, Any]) -> str:
    """
    Return a single-line text for the LLM:
    - textMessage -> textMessage
    - media with caption -> caption
    - media without caption -> short label (e.g., "🖼️ Image")
    """
    k = _kind(m)
    if k == "textmessage":
        return _norm(m.get("textMessage"))
    if k in ("imagemessage", "videomessage"):
        return _norm(m.get("caption")) or MEDIA_LABEL[k]
    if k in MEDIA_LABEL:
        return MEDIA_LABEL[k]
    # last resort: try common fields
    return _norm(m.get("textMessage")) or _norm(m.get("caption"))

def _message_id(m: Dict[str, Any]) -> str:
    return _norm(m.get("idMessage") or m.get("id") or "")

def _reference_id(m: Dict[str, Any]) -> str:
    """
    Try the common reply/quote keys Green-API / WA variants use.
    If nothing found, return '' (absent from the output later).
    """
    # direct keys
    ref = (
        m.get("quotedMessageId")
        or m.get("replyTo")
        or m.get("quotedStanzaID")
        or m.get("quotedMessageKey")
    )
    if isinstance(ref, str) and ref.strip():
        return ref.strip()

    # nested shapes some SDKs use
    qm = m.get("quotedMessage") or m.get("contextInfo") or {}
    if isinstance(qm, dict):
        for k in ("idMessage", "stanzaId", "stanzaID", "quotedMessageId"):
            v = qm.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

        # WhatsApp Web style: contextInfo -> quotedMessage -> key.id
        key = qm.get("key")
        if isinstance(key, dict):
            v = key.get("id")
            if isinstance(v, str) and v.strip():
                return v.strip()

    return ""

def minimize_chat_history(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Input: raw GreenAPI history items.
    Output: list of { "id": <idMessage>, "text": <single-line>[, "ref_id": <idMessage>] }
    - Sorted by (timestamp, idMessage) for determinism.
    - Skips items without an id or without any textual signal.
    """
    # sort for stable, chronological output
    msgs = sorted(
        messages,
        key=lambda m: (int(m.get("timestamp", 0)), _message_id(m))
    )

    out: List[Dict[str, str]] = []
    for m in msgs:
        mid = _message_id(m)
        if not mid:
            continue
        text = _message_text(m).strip()
        if not text:
            # If truly no human-readable content, skip
            continue

        item = {"id": mid, "text": text}
        ref = _reference_id(m)
        if ref:
            item["ref_id"] = ref
        out.append(item)

    return out

from datetime import datetime

from datetime import datetime

from datetime import datetime

def format_messages_for_llm(messages, as_string=True):
    """Convert raw WhatsApp messages into LLM-friendly summaries, including media URLs."""
    summaries = []
    for m in messages:
        sender = "Outgoing" if m.get("type") == "outgoing" else "Incoming"
        msg_type = m.get("typeMessage", "unknown")
        chat = m.get("chatId", "")
        ts = m.get("timestamp")
        time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "unknown time"

        # Default text/caption
        text = m.get("textMessage") or m.get("caption") or ""

        # Handle media URLs
        if msg_type in ["imageMessage", "videoMessage", "audioMessage",
                        "stickerMessage", "documentMessage"]:
            media_url = m.get("downloadUrl") or "[no URL]"
            text = f"{text} [media: {media_url}]".strip()

        summaries.append(f"{sender} {msg_type} to {chat} at {time_str} — {text}".strip())

    return "\n".join(summaries) if as_string else summaries

import requests

def normalize_chat_id(chat: str) -> str:
    """
    Normalize chat id / phone number for Green API:
    - Remove leading '+' if exists
    - If plain number, add '@c.us'
    - Leave group ids and valid chat ids unchanged
    """
    chat = chat.strip()

    # Remove leading '+'
    if chat.startswith("+"):
        chat = chat[1:]

    # Add @c.us if it's just a number
    if chat.isdigit():
        return f"{chat}@c.us"

    # Already in correct form (@c.us or @g.us)
    return chat


from green_api.chats_history import get_last_messages_for_user
@tool
async def search_chat_history(
    config: RunnableConfig, chat_id_to_search: str, chat_name_to_search: str, limit: int = 50
) -> dict:
    """
    Search chat history by chat ID. You can pass either:
      - Full chat JID like "9725XXXXXXXX@c.us" or "9725XXXXXXXX-YYYYYY@g.us"
      - Raw phone number like "9725XXXXXXXX" (with or without '+')
    The tool will normalize phone numbers to full JID automatically.

    Limit is clamped to 200.
    Returns: { ok: bool, chat_history: list, error?: str }
    """

    chat_id_to_search = normalize_chat_id(chat_id_to_search)

    print("search_chat_history: chat_id_to_search, chat_name_to_search, limit", chat_id_to_search, chat_name_to_search, limit)
    user_id = config["configurable"]["user_id"]
    start = pytime.time()

    try:
        limit = int(limit)
    except Exception:
        limit = 50
    limit = max(1, min(limit, MAX_LIMIT))

    try:
        chat_history = get_last_messages_for_user(user_id, chat_id_to_search, limit)
        print("search_chat_history: chat_history", chat_history)
        transcript = format_messages_for_llm(chat_history)
        print("search_chat_history: items", transcript)
    except Exception:
        logging.exception("Failed to fetch chat history for %s", chat_id_to_search)
        track_tool_call(
            user_id=user_id, tool="search_chat_history", op="search", item_type=None,
            ok=0, latency_ms=int((pytime.time() - start) * 1000), error_code="fetch_failed",
            extra={"limit": int(limit)}
        )
        return _fail("fetch_failed", {"chat_history": []})

    try_add_chat_to_recent_chats(user_id, chat_id_to_search, chat_name_to_search)
    logging.info("search_chat_history: %s → %s", chat_name_to_search, chat_id_to_search)

    results_count = len(transcript)
    track_tool_call(
        user_id=user_id, tool="search_chat_history", op="search", item_type=None,
        ok=1, latency_ms=int((pytime.time() - start) * 1000),
        extra={"limit": int(limit), "results_count": int(results_count), "truncated": 1 if results_count >= int(limit) else 0}
    )
    print("search_chat_history: transcript", transcript)
    return _ok({"chat_history": transcript})

# ----------------------
# get_candidate_recipient_chat_ids
# ----------------------
@tool
def get_candidate_recipient_chat_ids(config: RunnableConfig, recipient_name: str) -> list:
    """
    Get candidate chats for a recipient name.
    Accepts user.runtime.green_api_contacts as either:
      - Dict[str, str]  -> { name: chat_id }
      - List[Dict[str,str]] -> [ { name: chat_id }, ... ]
    Returns a list of { "name": str, "chat_id": str } sorted by match quality.
    """
    print("get_candidate_recipient_chat_ids: recipient_name", recipient_name)
    out: List[Dict[str, str]] = []  # ensure defined
    try:
        user_id = config["configurable"]["user_id"]
        start = pytime.time()
        user = get_user(user_id)

        mapping = user.runtime.green_api_contacts

        query = (recipient_name or "").strip().lower()
        results: List[Tuple[str, str]] = []
        for n, cid in mapping.items():
            if not n or not cid:
                continue
            if query in n.lower():
                results.append((n, cid))

        # Sort: prefix match first, then shorter names
        def sort_key(item: Tuple[str, str]):
            n = item[0].lower()
            return (0 if n.startswith(query) else 1, len(n))

        results.sort(key=sort_key)
        out = [{"name": n, "chat_id": cid} for n, cid in results]

        track_tool_call(
            user_id=user_id, tool="get_candidate_recipient_chat_ids", op="match",
            item_type=None, ok=1, latency_ms=int((pytime.time() - start) * 1000)
        )
        return out

    except Exception as e:
        print("get_candidate_recipient_chat_ids: failed", e)
        uid = config.get("configurable", {}).get("user_id", "unknown")
        track_tool_call(
            user_id=uid, tool="get_candidate_recipient_chat_ids", op="match",
            item_type=None, ok=0, latency_ms=0, error_code="internal_error"
        )
        return out  # empty on failure

from shared.user import normalize_phone
# ----------------------
# process_contact_message
# ----------------------
@tool(args_schema=ScheduledMessageItem)
def process_contact_message(config: RunnableConfig, **kwargs) -> dict:
    """
    Process a scheduled message to a contact by chat ID.
    For recipient_chat_id you can pass either:
      - Full chat JID (groups must have a jid)
      - Raw phone number like "9725XXXXXXXX" (with or without '+')
    The tool will normalize phone numbers to full JID automatically.

    Returns: { ok: bool, item_id: str|None, error?: str }
    """
    start = pytime.time()
    try:
        action = ScheduledMessageItem(**kwargs)
        user_id = config["configurable"]["user_id"]
        print("process_contact_message: action, userId", action, user_id)
        
        if action.command not in ("create", "update", "delete"):
            track_tool_call(
                user_id=user_id, tool="process_contact_message", op=str(action.command), item_type="message",
                ok=0, latency_ms=int((pytime.time() - start) * 1000), error_code="unknown_command"
            )
            print("process_contact_message: unknown_command", action.command)
            return _fail("unknown_command", {"item_id": None})

        if action.command == "create":
            dt = _parse_iso8601(action.scheduled_time)
            if not dt:
                track_tool_call(
                    user_id=user_id, tool="process_contact_message", op="create", item_type="message",
                    ok=0, latency_ms=int((pytime.time() - start) * 1000), error_code="invalid_datetime_format"
                )
                print("process_contact_message: invalid_datetime_format", action.scheduled_time)
                return _fail("invalid_datetime_format", {"item_id": None})

        elif action.command == "update" and action.scheduled_time is not None:
            if not _parse_iso8601(action.scheduled_time):
                track_tool_call(
                    user_id=user_id, tool="process_contact_message", op="update", item_type="message",
                    ok=0, latency_ms=int((pytime.time() - start) * 1000), error_code="invalid_datetime_format"
                )
                print("process_contact_message: invalid_datetime_format", action.scheduled_time)
                return _fail("invalid_datetime_format", {"item_id": None})

        store = ScheduledMessageStore()
        action.recipient_chat_id = normalize_phone(action.recipient_chat_id)
        try_add_chat_to_recent_chats(user_id, action.recipient_chat_id, action.recipient_name)
        logging.info("[TOOL] Processing scheduled message for user %s: %s", user_id, action)

        if action.command == "create":
            item_id = store.save(user_id=user_id, item=action)
            track_tool_call(
                user_id=user_id, tool="process_contact_message", op="create", item_type="message",
                ok=1, latency_ms=int((pytime.time() - start) * 1000)
            )
            return _ok({"item_id": item_id})

        if action.command == "update":
            if not (action.item_id or "").strip():
                track_tool_call(
                    user_id=user_id, tool="process_contact_message", op="update", item_type="message",
                    ok=0, latency_ms=int((pytime.time() - start) * 1000), error_code="missing_item_id"
                )
                print("process_contact_message: missing_item_id", action.item_id)
                return _fail("missing_item_id", {"item_id": None})
            allowed_updates = {
                "message": action.message,
                "scheduled_time": action.scheduled_time,
                "status": action.status,
            }
            store.update(item_id=action.item_id, updates=allowed_updates)
            track_tool_call(
                user_id=user_id, tool="process_contact_message", op="update", item_type="message",
                ok=1, latency_ms=int((pytime.time() - start) * 1000)
            )
            return _ok({"item_id": action.item_id})

        if action.command == "delete":
            if not (action.item_id or "").strip():
                track_tool_call(
                    user_id=user_id, tool="process_contact_message", op="delete", item_type="message",
                    ok=0, latency_ms=int((pytime.time() - start) * 1000), error_code="missing_item_id"
                )
                print("process_contact_message: missing_item_id", action.item_id)
                return _fail("missing_item_id", {"item_id": None})
            store.delete(item_id=action.item_id)
            track_tool_call(
                user_id=user_id, tool="process_contact_message", op="delete", item_type="message",
                ok=1, latency_ms=int((pytime.time() - start) * 1000)
            )
            return _ok({"item_id": action.item_id})

        # Shouldn't reach
        track_tool_call(
            user_id=user_id, tool="process_contact_message", op=str(action.command), item_type="message",
            ok=0, latency_ms=int((pytime.time() - start) * 1000), error_code="unknown_command"
        )
        print("process_contact_message: unknown_command", action.command)
        return _fail("unknown_command", {"item_id": None})

    except Exception:
        logging.exception("[TOOL] Failed to process scheduled message.")
        # Best-effort user_id from config in case of early failures
        uid = config.get("configurable", {}).get("user_id", "unknown")
        track_tool_call(
            user_id=uid, tool="process_contact_message", op=str(kwargs.get("command", "unknown")),
            item_type="message", ok=0, latency_ms=int((pytime.time() - start) * 1000),
            error_code="internal_error"
        )
        print("process_contact_message: unhandled_exception")
        return _fail("unhandled_exception", {"item_id": None})
