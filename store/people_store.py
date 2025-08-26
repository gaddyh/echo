from shared.user import get_user, create_user
from store.user import UserStore

def save_contacts_to_runtime(user_id: str, resolved_contacts: list[dict]) -> int:
    user = get_user(user_id)
    if user is None:
        create_user(user_id, "")

    user.runtime.contacts = {}

    for c in resolved_contacts:
        email = (c.get("email") or "").strip().lower()
        name = (c.get("displayName") or "").strip() or email
        if not name:
            continue
        user.runtime.contacts[name] = email

    print("save_contacts_to_runtime: ", user.runtime.contacts)

    UserStore(user_id).save(user)
    return len(user.runtime.contacts)
