from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Tuple

import logging

from infra.services.user_context_service import (  # noqa: F401
    ensure_name_multimap_lists,
    build_chatid_to_name,
    bump_recent_score,
    build_recent_name_map,
)

from shared.user import RECENT_CHATS_LIMIT

# ── Constants / Icons ──────────────────────────────────────────────────────────
TZ = ZoneInfo("Asia/Jerusalem")

DIR_ICON = {True: "🟦 Me", False: "🟩 Them"}
TYPE_ICON = {
    "chat": "💬",
    "image": "🖼️",
    "sticker": "🏷️",
    "audio": "🔊",     # use "🎤" if you prefer for PTT
    "video": "🎞️",
    "document": "📄",
    "location": "📍",
}

YES_THUMBS = {"👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿"}


# ── Small utilities ────────────────────────────────────────────────────────────
def format_ts(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), TZ).strftime("%Y-%m-%d %H:%M")


def ensure_name_multimap_lists(mapping: Any) -> Dict[str, List[str]]:
    """
    Coerce various legacy shapes into Dict[str, List[str]].
    - str -> [str]
    - set/tuple -> list
    - filter empties & dedupe keeping order
    """
    out: Dict[str, List[str]] = {}
    if isinstance(mapping, dict):
        for name, v in mapping.items():
            if not isinstance(name, str) or not name.strip():
                continue
            name_s = name.strip()
            if isinstance(v, str):
                seq = [v]
            elif isinstance(v, (list, tuple, set)):
                seq = list(v)
            else:
                # unknown → skip
                continue
            seen = set()
            lst: List[str] = []
            for cid in seq:
                if isinstance(cid, str):
                    cid_s = cid.strip()
                    if cid_s and cid_s not in seen:
                        seen.add(cid_s)
                        lst.append(cid_s)
            if lst:
                out[name_s] = lst
    return out


# ── GreenAPI parsing helpers ───────────────────────────────────────────────────
def is_me(m: dict) -> bool:
    # GreenAPI: 'type' == 'outgoing' means message sent by me
    return (m.get("type") or "").lower() == "outgoing"


def message_kind(m: dict) -> str:
    """Map GreenAPI typeMessage to normalized kind."""
    tm = (m.get("typeMessage") or "").lower()
    if not tm:
        # fallback if a client misuses 'type' for kind
        tm = (m.get("type") or "").lower()

    if tm in ("textmessage", "chat"):
        return "chat"
    if tm in ("imagemessage", "image"):
        return "image"
    if tm in ("videomessage", "video"):
        return "video"
    if tm in ("audiomessage", "ptt", "audio"):
        return "audio"
    if tm in ("sticker", "stickermessage"):
        return "sticker"
    if tm in ("documentmessage", "doc"):
        return "document"
    if tm in ("locationmessage", "location"):
        return "location"
    return "chat"


def extract_body(m: dict) -> str:
    """Human-readable text to display."""
    tm = (m.get("typeMessage") or "").lower()
    if tm == "textmessage":
        return m.get("textMessage") or ""
    if tm == "imagemessage":
        return m.get("caption") or ""
    if tm == "videomessage":
        return m.get("caption") or ""
    if tm in ("audiomessage", "ptt"):
        return "🎤 Voice note"
    if tm == "stickermessage":
        return "🏷️ Sticker"
    if tm == "documentmessage":
        return m.get("fileName") or "📄 Document"
    if tm == "locationmessage":
        return "📍 Location"
    # generic fallback
    return m.get("textMessage") or m.get("caption") or ""


def build_llm_history(messages: List[dict]) -> List[dict]:
    """Sort messages and attach sequential #refs + neighbors."""
    msgs = sorted(
        messages,
        key=lambda m: (int(m.get("timestamp", 0)), m.get("idMessage") or m.get("id") or "")
    )
    for i, m in enumerate(msgs, 1):
        m["_ref"] = f"#{i:03d}"
        m["_prev"] = f"#{i-1:03d}" if i > 1 else None
        m["_next"] = f"#{i+1:03d}" if i < len(msgs) else None
    return msgs


def render_line(m: dict) -> str:
    ts = format_ts(m.get("timestamp", 0))
    who = DIR_ICON[is_me(m)]
    kind = message_kind(m)
    icon = TYPE_ICON.get(kind, "💬")
    text = extract_body(m)
    ref = m.get("_ref", "")
    prev_ref = m.get("_prev")
    next_ref = m.get("_next")
    nav = []
    if prev_ref:
        nav.append(f"(prev:{prev_ref})")
    if next_ref:
        nav.append(f"(next:{next_ref})")
    body = f" • {text}" if text else ""
    return f"[{ref}] {ts} • {who} • {icon}{body} {' '.join(nav)}".rstrip()


# ── Contacts: chatId -> name builder ──────────────────────────────────────────
# (delegated to infra.services.user_context_service — re-exported here for backward compat)


# ── Recent chats computation ───────────────────────────────────────────────────
# (delegated to infra.services.user_context_service — re-exported here for backward compat)


# ── Example: rendering a fetched chat history (for your logs/diagnostics) ──────
def print_history_transcript(chat_history: List[dict]) -> None:
    items = build_refs(chat_history)
    for m in items:
        try:
            line = render_line(m)
        except Exception:
            # don't let one bad record stop the whole transcript
            logging.exception("Failed to render a message line")
            continue
        print("—")
        print(line)
