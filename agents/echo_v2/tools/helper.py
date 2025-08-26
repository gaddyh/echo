from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Tuple

import logging

# ── Your deps (assumed available) ───────────────────────────────────────────────
# get_user: (user_id) -> User
# UserStore(user_id).save(user)
# RECENT_CHATS_LIMIT: int
from shared.user import get_user, RECENT_CHATS_LIMIT
from store.user import UserStore

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


# ── Contacts: chatId -> name builder (supports multiple ids per name) ──────────
def build_chatid_to_name(contacts: Any) -> Dict[str, str]:
    """
    Returns { chatId: name }.

    Accepts:
      - List[{'id': str, 'name': str}] (optionally also 'contactName')
      - List[{name: id}]                (singleton dict)
      - Dict[name, id]                  (single id)
      - Dict[name, Iterable[id]]        (multiple ids per name)

    If a chat_id appears with different names, keeps the first non-empty name for stability.
    """
    mapping: Dict[str, str] = {}

    # Dict[name -> id or iterable[id]]
    if isinstance(contacts, dict):
        for name, cid_or_iter in contacts.items():
            if not isinstance(name, str) or not name.strip():
                continue
            name_s = name.strip()
            if isinstance(cid_or_iter, str):
                cid = cid_or_iter.strip()
                if cid:
                    mapping.setdefault(cid, name_s)
            elif isinstance(cid_or_iter, (list, tuple, set)):
                for cid in cid_or_iter:
                    if isinstance(cid, str) and cid.strip():
                        mapping.setdefault(cid.strip(), name_s)
        return mapping

    # List[…]
    if isinstance(contacts, list):
        for c in contacts:
            if not isinstance(c, dict):
                continue
            if "id" in c:
                cid = (c.get("id") or "").strip()
                # prefer 'name' then fallback to 'contactName'
                name = (c.get("name") or c.get("contactName") or "").strip()
                if cid and name:
                    mapping.setdefault(cid, name)
                continue
            # singleton {name: id}
            if len(c) == 1:
                (name, cid), = c.items()
                if isinstance(name, str) and isinstance(cid, str):
                    name_s, cid_s = name.strip(), cid.strip()
                    if name_s and cid_s:
                        mapping.setdefault(cid_s, name_s)
        return mapping

    return mapping


# ── Recent chats computation ───────────────────────────────────────────────────
def bump_recent_score(user: Any, chat_id: str, inc: int = 1) -> None:
    runtime = getattr(user, "runtime", None)
    if runtime is None:
        return
    if not hasattr(runtime, "recent_scores") or runtime.recent_scores is None:
        runtime.recent_scores = {}
    runtime.recent_scores[chat_id] = int(runtime.recent_scores.get(chat_id, 0)) + inc


def build_recent_name_map(
    user: Any,
    new_contact: Dict[str, Any] | None = None,
    limit: int = RECENT_CHATS_LIMIT,
) -> Tuple[Dict[str, str], List[Tuple[str, int]]]:
    """
    Returns:
      - name_to_chat_id: {display_name -> chat_id} for the top-N by score
      - top_list: [(chat_id, score)] sorted desc
    """
    runtime = getattr(user, "runtime", None)
    scores: Dict[str, int] = getattr(runtime, "recent_scores", {}) or {}
    if not scores:
        return {}, []

    # top by score, then chat_id for stability
    top_list = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]

    # Build chat_id -> preferred display name (from contacts cache)
    # Contacts cache can be legacy or new; normalize if necessary
    green_contacts = getattr(runtime, "green_api_contacts", {}) or {}
    # If it's name -> list[str], that's fine; if not, coerce.
    if isinstance(green_contacts, dict) and green_contacts and isinstance(next(iter(green_contacts.values())), list):
        chatid_to_name = build_chatid_to_name(green_contacts)
    else:
        chatid_to_name = build_chatid_to_name(ensure_name_multimap_lists(green_contacts))

    # Augment with new_contact if provided (without clobbering existing)
    if new_contact and isinstance(new_contact, dict):
        cid = (new_contact.get("id") or "").strip()
        nm = (new_contact.get("name") or "").strip()
        if cid and nm:
            chatid_to_name.setdefault(cid, nm)

    name_to_chat_id: Dict[str, str] = {}
    used_names = set()

    for chat_id, _score in top_list:
        base_name = chatid_to_name.get(chat_id, chat_id)
        name = base_name
        # Disambiguate if the same display name appears multiple times
        if name in used_names:
            digits = "".join(d for d in chat_id if d.isdigit())
            tail = (digits[-4:] if digits else chat_id[-4:]) or chat_id
            suffix = " (group)" if chat_id.endswith("@g.us") else ""
            name = f"{base_name}{suffix} • {tail}"

        name_to_chat_id[name] = chat_id
        used_names.add(name)

    return name_to_chat_id, top_list


def try_add_chat_to_recent_chats(user_id: str, recipient_chat_id: str, recipient_name: str) -> None:
    """
    - Bumps recent score for the chat
    - Ensures runtime.name2chat_id is Dict[str, List[str]]
    - Recomputes runtime.recent_chats (display map)
    - Persists user
    """
    try:
        print("try_add_chat_to_recent_chats:", user_id, recipient_chat_id, recipient_name)
        user = get_user(user_id)
        if not user:
            return
        runtime = getattr(user, "runtime", None)
        if runtime is None:
            return

        # 1) bump the score
        bump_recent_score(user, recipient_chat_id)

        # 2) normalize and append (lists, not sets)
        current = getattr(runtime, "name2chat_id", {}) or {}
        name2chat_ids: Dict[str, List[str]] = ensure_name_multimap_lists(current)
        lst = name2chat_ids.setdefault(recipient_name, [])
        if recipient_chat_id not in lst:
            lst.append(recipient_chat_id)
        runtime.name2chat_id = name2chat_ids

        # (optional) keep green_api_contacts in the same normalized shape
        gac = ensure_name_multimap_lists(getattr(runtime, "green_api_contacts", {}) or {})
        # Ensure it also has the recipient mapping
        gac.setdefault(recipient_name, [])
        if recipient_chat_id not in gac[recipient_name]:
            gac[recipient_name].append(recipient_chat_id)
        runtime.green_api_contacts = gac

        # 3) recompute recent display map
        recent_name_map, _ = build_recent_name_map(
            user, new_contact={"id": recipient_chat_id, "name": recipient_name}, limit=RECENT_CHATS_LIMIT
        )
        print("recent_name_map", recent_name_map)
        runtime.recent_chats = recent_name_map

        # 4) persist
        user_store = UserStore(user_id)
        user_store.save(user)

    except Exception:
        print("Failed to update recent chats")
        logging.exception("Failed to update recent chats")


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
