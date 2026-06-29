"""
tests/test_int_green_api.py

Verifies Green API connectivity:
  - contacts can be fetched for a real user
  - instance state can be queried
"""
import pytest
from shared.user import get_user
from green_api.contacts import get_all_contacts

pytestmark = pytest.mark.integration


def test_user_exists_in_firestore(real_user_id):
    """Confirms the test user record exists in Firestore."""
    user = get_user(real_user_id)
    assert user is not None, f"User {real_user_id} not found in Firestore"
    assert user.user_id == real_user_id


def test_user_has_green_api_instance(real_user_id):
    """Confirms the user has an active Green API instance."""
    user = get_user(real_user_id)
    assert user is not None
    assert user.runtime.greenApiInstance is not None, "No Green API instance on user"
    assert user.runtime.greenApiInstance.id, "Green API instance ID is empty"
    assert user.runtime.greenApiInstance.token, "Green API instance token is empty"


def test_contacts_fetch_returns_dict(real_user_id):
    """Confirms Green API returns a non-empty contacts dict."""
    contacts = get_all_contacts(real_user_id)
    assert isinstance(contacts, dict), "Expected dict from get_all_contacts"
    assert len(contacts) > 0, "Contacts dict is empty — check Green API instance state"


def test_instance_state_is_authorized(real_user_id):
    """Confirms the user's WhatsApp instance is authorized (logged in)."""
    from infra.app.server import get_instance_state
    state = get_instance_state(real_user_id)
    assert state == "authorized", (
        f"Instance state is '{state}' — the WhatsApp instance may need to be re-authenticated"
    )
