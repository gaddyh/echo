from pydantic import BaseModel
from typing import List
from typing import Dict

chat_store: Dict[str, Dict[str, 'ChatMetadata']] = {}

class ChatMetadata(BaseModel):
    chat_id: str
    chat_name: str
    is_group: bool
    is_self_group: bool
    participant_count: int
    participant_ids: List[str]
    participant_names: List[str]
    alias_tag: str | None = None

class GroupMetadataPayload(BaseModel):
    user_id: str
    chats: Dict[str, str]  # chat_name -> chat_id