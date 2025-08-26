from pydantic import BaseModel
from store.chat_index import UserChatIndexStore
from dotenv import load_dotenv
import os
from typing import Dict, List
from pydantic import Field
from context.scheduled_event import ScheduledEvent
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from typing import Any

load_dotenv(".venv/.env")

NODE_URL = os.getenv("NODE_URL", "http://localhost:3000")

class TokenUsage(BaseModel):
    prompt: int = 0
    completion: int = 0
    total: int = 0

class GreenApiInstance(BaseModel):
    token: str | None = None
    id: int | None = None

class UserRuntime(BaseModel):
    monthlyTokenUsage: Dict[str, TokenUsage] = Field(default_factory=dict)
    deploymentUrl: str | None = None
    actionAgentChatId: str | None = None

    name2chat_id: Dict[str, List[str]] = Field(default_factory=dict)
    recent_chats: Dict[str, str] = Field(default_factory=dict)
    recent_scores: Dict[str, int] = Field(default_factory=dict)
    green_api_contacts: Dict[str, List[str]] = Field(default_factory=dict)

    greenApiInstance: GreenApiInstance | None = Field(default_factory=GreenApiInstance)

    last_scheduled_message_received: str | None = None
    last_bot_reminder_received: str | None = None
    last_user_referenced_event: ScheduledEvent | None = None

    class Config:
        arbitrary_types_allowed = True
        fields = {"chatIndexStore": {"exclude": True}}

    @field_validator("name2chat_id", mode="before")
    def normalize_name2chat_id(cls, v: Any) -> Dict[str, List[str]]:
        if v is None:
            return {}

        if isinstance(v, dict):
            out: Dict[str, List[str]] = {}
            for k, val in v.items():
                if isinstance(val, str):
                    out[k] = [val]
                elif isinstance(val, list):
                    out[k] = [x for x in val if isinstance(x, str)]
                else:
                    out[k] = []
            return out

        if isinstance(v, list):
            merged: Dict[str, List[str]] = {}
            for item in v:
                if isinstance(item, dict):
                    for k, val in item.items():
                        if isinstance(val, str):
                            merged.setdefault(k, []).append(val)
                        elif isinstance(val, list):
                            merged.setdefault(k, []).extend(
                                [x for x in val if isinstance(x, str)]
                            )
            return merged

        if isinstance(v, str):
            return {"Unknown": [v]}

        return {}

class UserConfig(BaseModel):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Time the user was created. auto-generated.")
    status: Literal["trial", "active", "inactive"] = "trial"
    name: str
    timezone: str
    language: str
    preferences: dict = {}

class User(BaseModel):
    user_id: str
    config: UserConfig
    runtime: UserRuntime

userContextDict: dict[str, User] = {}
