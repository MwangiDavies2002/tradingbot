"""Loopback-only UI test server: temporary SQLite, real research routes, no broker startup."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from contextlib import asynccontextmanager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
temporary = tempfile.TemporaryDirectory(prefix="mrbot-ui-")
original_directory = Path.cwd()
os.chdir(temporary.name)  # Never read the application's .env.
os.environ.update(DERIV_APP_ID="visual-test", DERIV_API_TOKEN="visual-test-unused",
                  SECRET_KEY="visual-test-only-no-broker-connection", ENVIRONMENT="development", DEBUG="false",
                  DATABASE_URL="sqlite+aiosqlite:///" + (Path(temporary.name) / "ui.db").as_posix(),
                  LIVE_TRADING_ENABLED="false", DERIV_DEMO="true")
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
os.chdir(original_directory)
from app.database.session import engine
from app.database.models import Base
from app.api.security import protect_api
from app.api.routes import institutional, instrument_catalog, research_registry

settings.API_ADMIN_KEY_HASH = hashlib.sha256(b"visual-test-admin-key-0000000000000000").hexdigest()
settings.API_OPERATOR_KEY_HASH = hashlib.sha256(b"visual-test-operator-key-0000000000000000").hexdigest()
settings.API_VIEWER_KEY_HASH = hashlib.sha256(b"visual-test-viewer-key-0000000000000000").hexdigest()


@asynccontextmanager
async def lifespan(app):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.middleware("http")(protect_api)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:4173"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(institutional.router, prefix="/api/institutional")
app.include_router(instrument_catalog.router, prefix="/api/instruments")
app.include_router(research_registry.router, prefix="/api/research-registry")


@app.get("/api/auth/me")
async def identity(request: Request):
    return {"role": request.state.role, "demo": True, "account_id": "SYNTHETIC UI TEST"}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8017)
