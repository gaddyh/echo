from typing import Dict, List
from collections import defaultdict
from difflib import get_close_matches
from context.chat_metadata import ChatMetadata, GroupMetadataPayload
from db.base import db

class UserChatIndexStore:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.db = db

        # In-memory index
        self.name_to_chat_ids: Dict[str, List[str]] = defaultdict(list)
        self.alias_to_chat_ids: Dict[str, List[str]] = defaultdict(list)
        self.chat_id_to_name: Dict[str, str] = {}
        self.lower_index: Dict[str, str] = {}

    def load_from_firestore(self):
        self.clear_maps()
        chat_docs = self.db.collection("users").document(self.user_id).collection("chat_metadata").get()
        for doc in chat_docs:
            data = doc.to_dict()
            chat = ChatMetadata(**data)
            self.add_chat_to_memory(chat)

    def save_all(self, payload: GroupMetadataPayload):
        for chat in payload.chats:
            self.db.collection("users").document(self.user_id).collection("chat_metadata") \
                .document(chat.chat_id).set(chat.model_dump())
            self.add_chat_to_memory(chat)

    def get_chat_name(self, chat_id: str) -> str:
        return self.chat_id_to_name.get(chat_id, "")

    def resolve_chat_candidates(self, name: str, max_results: int = 5) -> List[Dict[str, str]]:
        """
        Attempts to resolve the input `name` to matching chats.
        Returns a list of dictionaries: {match_type, chat_id, chat_name}
        """
        seen = set()
        results: List[Dict[str, str]] = []
        lowered = name.lower()

        # 1. Case-insensitive match
        if lowered in self.lower_index:
            chat_id = self.lower_index[lowered]
            if chat_id not in seen:
                results.append({
                    "match_type": "exact",
                    "chat_id": chat_id,
                    "chat_name": self.chat_id_to_name.get(chat_id, "")
                })
                seen.add(chat_id)

        # 2. Alias match
        if name in self.alias_to_chat_ids:
            for chat_id in self.alias_to_chat_ids[name]:
                if chat_id not in seen:
                    results.append({
                        "match_type": "alias",
                        "chat_id": chat_id,
                        "chat_name": self.chat_id_to_name.get(chat_id, "")
                    })
                    seen.add(chat_id)

        # 3. Name match
        if name in self.name_to_chat_ids:
            for chat_id in self.name_to_chat_ids[name]:
                if chat_id not in seen:
                    results.append({
                        "match_type": "name",
                        "chat_id": chat_id,
                        "chat_name": self.chat_id_to_name.get(chat_id, "")
                    })
                    seen.add(chat_id)

        # 4. Fuzzy match
        if len(results) < max_results:
            fuzzy_matches = self.fuzzy_search(name, n=max_results - len(results))
            for _, chat_id in fuzzy_matches:
                if chat_id not in seen:
                    results.append({
                        "match_type": "fuzzy",
                        "chat_id": chat_id,
                        "chat_name": self.chat_id_to_name.get(chat_id, "")
                    })
                    seen.add(chat_id)

        return results

    def fuzzy_search(self, query: str, n: int = 3, cutoff: float = 0.6) -> List[tuple[str, str]]:
        keys = list(self.lower_index.keys())
        matches = get_close_matches(query.lower(), keys, n=n, cutoff=cutoff)
        return [(match, self.lower_index[match]) for match in matches]

    def add_chat_to_memory(self, chat: ChatMetadata):
        self.chat_id_to_name[chat.chat_id] = chat.chat_name
        if chat.chat_name:
            self.name_to_chat_ids[chat.chat_name].append(chat.chat_id)
            self.lower_index[chat.chat_name.lower()] = chat.chat_id
        if chat.alias_tag:
            self.alias_to_chat_ids[chat.alias_tag].append(chat.chat_id)
            self.lower_index[chat.alias_tag.lower()] = chat.chat_id

    def clear_maps(self):
        self.name_to_chat_ids.clear()
        self.alias_to_chat_ids.clear()
        self.chat_id_to_name.clear()
        self.lower_index.clear()


from collections import defaultdict
from typing import Dict, Set
import re

class NamePhoneIndex:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.db = db
        self.name_to_phones: Dict[str, Set[str]] = defaultdict(set)

    def load_from_firestore(self):
        chat_docs = self.db.collection("users").document(self.user_id).collection("chat_metadata").get()
        for doc in chat_docs:
            data = doc.to_dict()
            chat = ChatMetadata(**data)
            self._process_chat(chat)

    def _process_chat(self, chat: ChatMetadata):
        for name, pid in zip(chat.participant_names, chat.participant_ids):
            phone = self._extract_phone(pid)
            if phone:
                self.name_to_phones[name].add(phone)

    def _extract_phone(self, participant_id: str) -> str:
        # Example formats: "972541234567@s.whatsapp.net", "12345@lid"
        match = re.match(r"(\d+)", participant_id)
        return match.group(1) if match else ""

    def get_index(self) -> Dict[str, Set[str]]:
        return self.name_to_phones
