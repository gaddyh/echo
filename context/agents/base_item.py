from typing import Optional, Literal
from pydantic import BaseModel

class BaseActionItem(BaseModel):
    # Optional for create, required for update/delete (we enforce this in the tool)
    item_id: Optional[str] = None

    command: Literal["create", "update", "delete"]
    item_type: Literal["reminder", "task", "event"]  # discriminator
    title: str
    description: Optional[str] = None
    status: Optional[str] = None
    op_id: Optional[str] = None  # idempotency
