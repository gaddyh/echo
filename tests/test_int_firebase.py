"""
tests/test_int_firebase.py

Verifies Firestore connectivity and read/write permissions.
Writes a sentinel document, reads it back, then deletes it.
"""
import pytest
from db.base import db

pytestmark = pytest.mark.integration


def test_firestore_write_read_delete():
    col = db.collection("_integration_tests")
    doc_ref = col.document("ping")

    doc_ref.set({"value": "pong", "source": "echo-int-test"})

    snap = doc_ref.get()
    assert snap.exists, "Document was not created in Firestore"
    data = snap.to_dict()
    assert data["value"] == "pong"
    assert data["source"] == "echo-int-test"

    doc_ref.delete()
    assert not doc_ref.get().exists, "Document was not deleted"


def test_firestore_collection_list():
    """Confirms collection-level queries work (needed by stores)."""
    col = db.collection("_integration_tests")
    docs = list(col.limit(1).stream())
    # Just confirm the query runs without raising — collection may be empty
    assert isinstance(docs, list)
