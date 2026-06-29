# apps/bot.py — DEPRECATED: server has moved to infra/app/server.py
# This shim keeps `uvicorn apps.bot:app` working.
from infra.app.server import app  # noqa: F401

if __name__ == "__main__":
    import os, uvicorn
    uvicorn.run("infra.app.server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
