from dataclasses import dataclass
from typing import Optional
from pydantic import BaseModel

@dataclass
class MediaInfo:
    url: Optional[str]
    mime_type: Optional[str]
    caption: Optional[str] = None
    sha256: Optional[str] = None
    media_id: Optional[str] = None  # e.g. from image['id']

class Media(BaseModel):
    mimetype: str
    filename: Optional[str] = None
    data: str