from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Jerusalem")

DIR_ICON = {True: "🟦 Me", False: "🟩 Them"}
TYPE_ICON = {
    "chat": "💬",
    "image": "🖼️",
    "sticker": "🏷️",
    "ptt": "🎤",      # push-to-talk voice
    "audio": "🔊",
    "video": "🎞️",
    "album": "🗂️",
    "document": "📄",
    "location": "📍",
    "reaction": "💟",
}

YES_THUMBS = {"👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿"}

def format_ts(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), TZ).strftime("%Y-%m-%d %H:%M")

def normalize_type(t: str) -> str:
    return TYPE_ICON.get((t or "chat").lower(), "💬")

def build_refs(messages: list[dict]) -> list[dict]:
    """Sort messages and attach sequential #refs + neighbors."""
    msgs = sorted(messages, key=lambda m: (m.get("timestamp", 0), m.get("id", "")))
    for i, m in enumerate(msgs, start=1):
        m["_ref_num"] = i
        m["_ref"] = f"#{i:03d}"
        m["_prev_ref"] = f"#{i-1:03d}" if i > 1 else None
        m["_next_ref"] = f"#{i+1:03d}" if i < len(msgs) else None
    return msgs

def index_id_to_ref(msgs: list[dict]) -> dict[str, str]:
    """Map raw message id -> #ref for reaction resolution."""
    return {m.get("id"): m["_ref"] for m in msgs if m.get("id")}

def normalize_body_intent_and_reaction(m: dict, id_to_ref: dict[str, str]) -> tuple[str, str|None, str|None]:
    """
    Returns (body_text, intent, reaction_to_ref)
    - Maps 👍 to 'affirmative' whether in text or as a reaction
    - Resolves reaction target to #ref if possible
    """
    body = (m.get("body") or "").strip()
    intent = None
    reaction_to_ref = None
    mtype = (m.get("type") or "").lower()

    # Case 1: thumbs-up as normal chat message body
    if body in YES_THUMBS:
        return "👍 (YES)", "affirmative", None

    # Case 2: reaction payloads
    if mtype == "reaction" or isinstance(m.get("reaction"), dict):
        rx = m.get("reaction") or {}
        emoji = rx.get("emoji") or body  # some providers echo emoji in body too
        target_id = rx.get("msg_id") or rx.get("message_id") or rx.get("to") or None
        if target_id and target_id in id_to_ref:
            reaction_to_ref = id_to_ref[target_id]
        # thumbs-up reaction => affirmative
        if emoji in YES_THUMBS:
            return "👍 (YES)", "affirmative", reaction_to_ref
        # other reactions: surface the emoji so LLM can see it
        disp = emoji if emoji else (body if body else "💟")
        return disp, None, reaction_to_ref

    # Default
    return body, intent, reaction_to_ref

def to_structured_items(msgs: list[dict]) -> list[dict]:
    """Compact items with icons, refs, intents, and reaction linkage."""
    id_to_ref = index_id_to_ref(msgs)
    items = []
    for m in msgs:
        body, intent, reaction_to_ref = normalize_body_intent_and_reaction(m, id_to_ref)
        items.append({
            "ref": m["_ref"],
            "prev_ref": m["_prev_ref"],
            "next_ref": m["_next_ref"],
            "id": m.get("id"),
            "when": format_ts(m.get("timestamp", 0)),
            "who": DIR_ICON.get(m.get("fromMe", False), "🟩 Them"),
            "kind": normalize_type(m.get("type", "chat")),
            "body": body,
            "intent": intent,                     # e.g., "affirmative" for 👍
            "reaction_to_ref": reaction_to_ref,   # e.g., "#042" if this is a reaction
        })
    return items

def render_transcript(items: list[dict]) -> str:
    """Human/LLM-friendly transcript lines with refs + reaction arrow."""
    lines = []
    for it in items:
        header = f"[{it['ref']}] {it['when']} • {it['who']} • {it['kind']}"
        chain = []
        if it["prev_ref"]:
            chain.append(f"prev:{it['prev_ref']}")
        if it["next_ref"]:
            chain.append(f"next:{it['next_ref']}")
        chain_str = f"  ({', '.join(chain)})" if chain else ""

        body = it["body"]
        if it.get("reaction_to_ref"):
            # Use a clear reply arrow to the resolved #ref
            body = f"{body}  ↩︎ {it['reaction_to_ref']}"

        if body:
            lines.append(f"{header}{chain_str}\n{body}")
        else:
            lines.append(f"{header}{chain_str}")
        lines.append("—")
    if lines:
        lines.pop()
    return "\n".join(lines)

def build_llm_history(payload: dict) -> tuple[str, list[dict]]:
    """
    Input: {'messages': [ ... ]}
    Output:
      - transcript string (icons + refs + reaction ↩︎ #NNN)
      - structured items (refs, kind, who, body, intent, reaction_to_ref)
    """
    raw = payload.get("messages", [])
    msgs = build_refs(raw)
    items = to_structured_items(msgs)
    transcript = render_transcript(items)
    return transcript, items

# --- Example usage ---
# data = {...}  # your JSON
# transcript, items = build_llm_history(data)
# print(transcript)
# # items is ready to feed as structured context to your LLM/tooling
