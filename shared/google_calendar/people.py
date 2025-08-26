import re
from typing import Callable, Optional, Tuple, List, Dict

EMAIL_RE = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$")

def _normalize_email(raw: str) -> Optional[str]:
    if not raw:
        return None
    e = raw.strip().strip("<>").strip().strip('"').strip("'").lower()
    # common garbage: angle-brackets, quoted strings, stray spaces
    if EMAIL_RE.match(e):
        return e
    return None

def _pick_primary_email(contact: dict) -> Optional[Tuple[str, str]]:
    """Return (email, email_source) from People API contact or None."""
    emails = contact.get("emailAddresses") or []
    if not emails:
        return None
    primary = next((e for e in emails if e.get("metadata", {}).get("primary")), emails[0])
    norm = _normalize_email(primary.get("value", ""))
    if not norm:
        # try any other usable email
        for e in emails:
            norm2 = _normalize_email(e.get("value", ""))
            if norm2:
                return norm2, ("people.primary" if e is primary else "people.first")
        return None
    return norm, "people.primary"

def resolve_contacts(
    people: List[dict],
    *,
    directory_lookup: Optional[Callable[[str], Optional[str]]] = None,
    manual_lookup: Optional[Callable[[Dict[str, str]], Optional[str]]] = None,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Input: list of Google People API person dicts.
    Output:
      - resolved: [{resourceName, displayName, email, email_source, status, notes?}]
      - needs_email: same shape, status='needs_email' and email=None
    You can pass:
      - directory_lookup(display_name) -> email|None
      - manual_lookup(contact_dict_for_prompt) -> email|None  (e.g., ask via WhatsApp)
    """
    resolved: List[Dict[str, str]] = []
    missing: List[Dict[str, str]] = []

    for p in people:
        resource = p.get("resourceName", "")
        names = p.get("names") or [{}]
        display = (
            names[0].get("displayName")
            or names[0].get("unstructuredName")
            or names[0].get("displayNameLastFirst")
            or "ללא שם"
        ).strip()

        picked = _pick_primary_email(p)
        email, source = (picked if picked else (None, None))

        notes = []

        if not email and directory_lookup:
            d_email = _normalize_email(directory_lookup(display))
            if d_email:
                email, source = d_email, "workspace.directory"

        if not email and manual_lookup:
            m_email = _normalize_email(manual_lookup({"resourceName": resource, "displayName": display}))
            if m_email:
                email, source = m_email, "manual"

        # Optional: mark no-reply style as not invite-worthy
        if email and email.startswith("no-reply@"):
            notes.append("auto: no-reply address")

        record = {
            "resourceName": resource,
            "displayName": display,
            "email": email or "",
            "email_source": source or "",
            "status": "ok" if email else "needs_email",
        }
        if notes:
            record["notes"] = "; ".join(notes)

        if email:
            resolved.append(record)
        else:
            missing.append(record)

    # de-duplicate by normalized email (keep the most informative displayName)
    seen = {}
    deduped: List[Dict[str, str]] = []
    for r in resolved:
        key = r["email"]
        if key not in seen or len(r.get("displayName", "")) > len(seen[key].get("displayName", "")):
            seen[key] = r
    deduped = list(seen.values())

    return deduped, missing
