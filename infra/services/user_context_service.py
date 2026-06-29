from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from shared.user import get_user, RECENT_CHATS_LIMIT
from store.user import UserStore

from domain.inbound import UserContext

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

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

    if isinstance(contacts, list):
        for c in contacts:
            if not isinstance(c, dict):
                continue
            if "id" in c:
                cid = (c.get("id") or "").strip()
                name = (c.get("name") or c.get("contactName") or "").strip()
                if cid and name:
                    mapping.setdefault(cid, name)
                continue
            if len(c) == 1:
                (name, cid), = c.items()
                if isinstance(name, str) and isinstance(cid, str):
                    name_s, cid_s = name.strip(), cid.strip()
                    if name_s and cid_s:
                        mapping.setdefault(cid_s, name_s)
        return mapping

    return mapping


def bump_recent_score(user: Any, chat_id: str, inc: int = 1) -> None:
    runtime = getattr(user, "runtime", None)
    if runtime is None:
        return
    if not hasattr(runtime, "recent_scores") or runtime.recent_scores is None:
        runtime.recent_scores = {}
    runtime.recent_scores[chat_id] = int(runtime.recent_scores.get(chat_id, 0)) + inc


def build_recent_name_map(
    user: Any,
    new_contact: Optional[Dict[str, Any]] = None,
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

    top_list = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]

    green_contacts = getattr(runtime, "green_api_contacts", {}) or {}
    if isinstance(green_contacts, dict) and green_contacts and isinstance(next(iter(green_contacts.values())), list):
        chatid_to_name = build_chatid_to_name(green_contacts)
    else:
        chatid_to_name = build_chatid_to_name(ensure_name_multimap_lists(green_contacts))

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

        bump_recent_score(user, recipient_chat_id)

        current = getattr(runtime, "name2chat_id", {}) or {}
        name2chat_ids: Dict[str, List[str]] = ensure_name_multimap_lists(current)
        lst = name2chat_ids.setdefault(recipient_name, [])
        if recipient_chat_id not in lst:
            lst.append(recipient_chat_id)
        runtime.name2chat_id = name2chat_ids

        gac = ensure_name_multimap_lists(getattr(runtime, "green_api_contacts", {}) or {})
        gac.setdefault(recipient_name, [])
        if recipient_chat_id not in gac[recipient_name]:
            gac[recipient_name].append(recipient_chat_id)
        runtime.green_api_contacts = gac

        recent_name_map, _ = build_recent_name_map(
            user, new_contact={"id": recipient_chat_id, "name": recipient_name}, limit=RECENT_CHATS_LIMIT
        )
        print("recent_name_map", recent_name_map)
        runtime.recent_chats = recent_name_map

        user_store = UserStore(user_id)
        user_store.save(user)

    except Exception:
        print("Failed to update recent chats")
        logger.exception("Failed to update recent chats")


# ── UserContextService ─────────────────────────────────────────────────────────

class UserContextService:
    """Implements domain.ports.UserContextService."""

    def get(self, user_id: str) -> Optional[UserContext]:
        user = get_user(user_id)
        if not user:
            return None
        return UserContext(
            user_id=user.user_id,
            name=user.config.name,
            timezone=user.config.timezone,
            recent_chats=dict(user.runtime.recent_chats or {}),
            name2chat_id=dict(user.runtime.name2chat_id or {}),
        )

    def remember_chat(self, user_id: str, chat_id: str, name: str) -> None:
        try_add_chat_to_recent_chats(user_id, chat_id, name)

    def save_token_usage(self, user_id: str, month: str, delta_tokens: int) -> None:
        from shared.user import get_user, TokenUsage
        from store.user import UserStore
        user = get_user(user_id)
        if not user:
            return
        usage = user.runtime.monthlyTokenUsage.setdefault(month, TokenUsage())
        usage.total += delta_tokens
        UserStore(user_id).save(user)
