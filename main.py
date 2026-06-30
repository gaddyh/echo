# main.py — entry point for `uvicorn main:app --host 0.0.0.0 --port $PORT`
from infra.app.server import app  # noqa: F401
