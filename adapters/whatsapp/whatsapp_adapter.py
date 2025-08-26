# adapters/whatsapp/whatsapp_adapter.py

from abc import ABC, abstractmethod
from typing import Dict, Any
from context.message.raw_message import RawMessage

# in bot the identity is the sender, only incoming is interesting
# in whatsmatter the identity is the whatsapp account itself, outgoing is the most interesting
class WhatsAppAdapter(ABC):
    @abstractmethod
    async def parse_incoming(self, data: dict) -> RawMessage | None:
        """
        Extract a standard incoming message:
        { "sender": str, "text": str, "timestamp": int, "message_id": str }
        """
        pass

    @abstractmethod
    async def send_message(self, webhook_uid: str, recipient: str, message: str) -> dict:
        """
        Send a message to a recipient.
        webhook_uid allows sending on behalf of specific user instances.
        """
        pass

    @abstractmethod
    def get_identity(self, webhook_uid: str) -> dict:
        """
        Fetch instance credentials and identity for a given webhook UID.
        Example return:
        { "instanceId": str, "token": str, "phone": str }
        """
        pass

    @abstractmethod
    def detect_direction(self, data: dict) -> str:
        """
        Determine message direction: "incoming", "outgoing", or "other".
        """
        pass

    @abstractmethod
    def init_message_context(self, webhook_uid: str, message_direction: str, data: Dict[str, Any]) -> RawMessage:
        """
        Initialize a RawMessage object (or adapter-specific equivalent) from raw data.
        """
        pass