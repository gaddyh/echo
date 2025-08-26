import os
from typing import Optional
from dotenv import load_dotenv
load_dotenv(".venv/.env")

def require_env(var_name: str, default: Optional[str] = None) -> str:
    val = os.getenv(var_name)
    if not val:
        if default is None:
            raise ValueError(f"Missing required environment variable: {var_name}")
        val = default
    return val

GREEN_API_PARTNER_API_URL = require_env("GREEN_API_PARTNER_API_URL", "https://api.green-api.com")
GREEN_API_PARTNER_TOKEN = require_env("GREEN_API_PARTNER_TOKEN")