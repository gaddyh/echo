

from google.cloud import firestore
from shared import time
from shared.delivery_mng import SendingStatus
from db.base import db

class SendingStatusStore:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.collection = db.collection("sending_status").document(user_id).collection("items")

    def _doc_id(self, item_type: str, item_id: str) -> str:
        return f"{item_type}_{item_id}"

    def get(self, item_id: str, item_type: str) -> dict | None:
        doc = self.collection.document(self._doc_id(item_type, item_id)).get()
        return doc.to_dict() if doc.exists else None

    def create_or_get(self, item_id: str, item_type: str) -> dict:
        doc_ref = self.collection.document(self._doc_id(item_type, item_id))
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        status = SendingStatus(item_type=item_type, item_id=item_id, user_id=self.user_id).dict()
        doc_ref.set(status)
        return status

    def update(self, item_id: str, item_type: str, **fields):
        doc_ref = self.collection.document(self._doc_id(item_type, item_id))
        fields["last_attempt"] = time.utcnow()
        doc_ref.set(fields, merge=True)

    def increment_retry(self, item_id: str, item_type: str) -> int:
        doc_ref = self.collection.document(self._doc_id(item_type, item_id))
        doc = doc_ref.get()
        retries = 0
        if doc.exists:
            retries = doc.to_dict().get("retry_count", 0) + 1
        doc_ref.set({"retry_count": retries, "last_attempt": time.utcnow()}, merge=True)
        return retries

    def reset_retry(self, item_id: str, item_type: str):
        doc_ref = self.collection.document(self._doc_id(item_type, item_id))
        doc_ref.set({"retry_count": 0}, merge=True)

