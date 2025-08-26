from dataclasses import dataclass
from typing import Optional

@dataclass
class LocationInfo:
    latitude: float
    longitude: float
    name: Optional[str] = None
    address: Optional[str] = None