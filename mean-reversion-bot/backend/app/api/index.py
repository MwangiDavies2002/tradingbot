"""
api/index.py
────────────────────────────────────────────────────────────────────────────
Vercel serverless entrypoint for the FastAPI app.

Vercel's Python runtime looks for a variable named `app` (an ASGI app)
in this file. We import the real FastAPI app from backend/app/main.py.
────────────────────────────────────────────────────────────────────────────
"""

import os
import sys

# Add the backend/ directory to sys.path so `app.main` is importable,
# since backend/ is a sibling of api/, not a package itself.
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

from app.main import app  # noqa: E402