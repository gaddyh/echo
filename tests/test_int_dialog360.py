"""
tests/test_int_dialog360.py

Verifies the 360dialog webhook endpoint using FastAPI's TestClient.
The LLM/assistant layer is mocked so these tests incur zero API cost
and pass without an OpenAI key.

Verifies:
  - Requests without Authorization header → 401
  - Duplicate message IDs → deduplicated (status: duplicate)
  - Synthetic text message payload → parsed and handled (200)
"""
import os
import pytest
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
AUTH_HEADER = {"Authorization": f"Bearer {WEBHOOK_SECRET}"}

_TEXT_PAYLOAD = {
    "entry": [{
        "changes": [{
            "value": {
                "messages": [{
                    "id": "wamid.test123",
                    "from": "972500000001",
                    "type": "text",
                    "text": {"body": "שלום"},
                    "timestamp": "1700000000",
                }],
                "contacts": [{"profile": {"name": "Test User"}, "wa_id": "972500000001"}],
            }
        }]
    }]
}


@pytest.fixture(scope="module")
def client():
    """TestClient with assistant.handle mocked out."""
    from infra.app.server import app
    import infra.app.wiring as wiring

    mock_assistant = AsyncMock()
    mock_assistant.handle = AsyncMock(return_value="תשובה בדיקה")

    with patch.object(wiring, "assistant", mock_assistant):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def test_missing_auth_returns_401(client):
    resp = client.post("/webhook/whatsapp", json=_TEXT_PAYLOAD)
    assert resp.status_code == 401


def test_wrong_secret_returns_401(client):
    resp = client.post(
        "/webhook/whatsapp",
        json=_TEXT_PAYLOAD,
        headers={"Authorization": "Bearer wrong-secret"},
    )
    assert resp.status_code == 401


def test_text_message_handled(client):
    resp = client.post("/webhook/whatsapp", json=_TEXT_PAYLOAD, headers=AUTH_HEADER)
    assert resp.status_code == 200
    assert resp.json()["status"] == "received"


def test_duplicate_message_deduplicated(client):
    """Second POST with the same message ID should return status=duplicate."""
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "wamid.dedup_test_999",
                        "from": "972500000002",
                        "type": "text",
                        "text": {"body": "כפל"},
                        "timestamp": "1700000001",
                    }],
                    "contacts": [{"profile": {"name": "Dedup"}, "wa_id": "972500000002"}],
                }
            }]
        }]
    }
    first = client.post("/webhook/whatsapp", json=payload, headers=AUTH_HEADER)
    assert first.status_code == 200

    second = client.post("/webhook/whatsapp", json=payload, headers=AUTH_HEADER)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"


def test_empty_body_ignored(client):
    resp = client.post("/webhook/whatsapp", json={}, headers=AUTH_HEADER)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
