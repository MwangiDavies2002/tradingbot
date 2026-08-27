"""Vercel serverless entry point for the FastAPI dashboard API."""

import os
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("VERCEL_SERVERLESS", "1")

from app.main import app  # noqa: E402
